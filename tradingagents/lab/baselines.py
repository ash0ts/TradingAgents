"""Numerical methods use frozen prices only, with purged chronological validation."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from tradingagents.lab.evidence import EvidenceStore, canonical, digest
from tradingagents.lab.protocol import cases
from tradingagents.lab.scoring import score

NAMES = ["cash", "SPY", "equal-weight", "momentum-20", "mean-reversion-5", "AR-5", "ridge", "XGBoost", "DLinear", "chronos-bolt-small"]
THRESHOLDS = [-.01, -.0025, .0025, .01]


def rating_for(forecast):
    return ["Sell", "Underweight", "Hold", "Overweight", "Buy"][int(np.searchsorted(THRESHOLDS, forecast, side="right"))]


@dataclass
class Prediction:
    rating: str
    forecast: float | None
    details: dict
    information_access: str = "prices and corporate actions through cutoff; no text"


class Predictor(Protocol):
    def predict(self, bundle: dict, fit_before: str) -> Prediction: ...


def indices(bundle):
    ticker = bundle["case"]["ticker"]
    stock = {r["date"]: r for r in bundle["prices"][ticker]}
    bench = {r["date"]: r for r in bundle["prices"]["SPY"]}
    dates = sorted(stock.keys() & bench.keys())
    series = []
    for table in [stock, bench]:
        values = [100.0]
        for previous, date in zip(dates, dates[1:], strict=False):
            row = table[date]
            growth = (row["close"] + row["dividend"]) * (row["split"] or 1) / table[previous]["close"]
            values.append(values[-1] * growth)
        series.append(np.array(values))
    return dates, series[0], series[1]


def hold_return(rows, start, end):
    shares, cash = 1.0, 0.0
    for row in rows[start + 1:end + 1]:
        shares *= row["split"] or 1
        cash += shares * row["dividend"]
    return (shares * rows[end]["close"] + cash) / rows[start]["close"] - 1


def supervised(bundle, fit_before, lag=20, horizon=5):
    dates, stock, bench = indices(bundle)
    returns = np.diff(np.log(stock)) - np.diff(np.log(bench))
    stock_rows = {r["date"]: r for r in bundle["prices"][bundle["case"]["ticker"]]}
    bench_rows = {r["date"]: r for r in bundle["prices"]["SPY"]}
    sr, br = [stock_rows[d] for d in dates], [bench_rows[d] for d in dates]
    x, y, exits = [], [], []
    for i in range(lag, len(dates) - horizon - 1):
        end = i + 1 + horizon
        if dates[end] >= fit_before:
            continue
        x.append(returns[i-lag:i])
        y.append(hold_return(sr, i+1, end) - hold_return(br, i+1, end))
        exits.append(dates[end])
    if len(x) < 100:
        raise ValueError("Insufficient matured training data")
    split = int(len(x) * .8)
    # Purge overlapping labels between training and validation.
    train_end = split - horizon - 1
    return (np.array(x[:train_end]), np.array(y[:train_end]), np.array(x[split:]), np.array(y[split:]),
            returns[-lag:].reshape(1, -1), {"training_labels": train_end, "validation_labels": len(x)-split,
                                         "last_training_exit": exits[train_end-1], "last_validation_exit": exits[-1],
                                         "fit_before": fit_before, "data_sha256": digest({"x": np.array(x).tolist(), "y": y})})


class NumericPredictor:
    def __init__(self, name, model_dir, chronos_path=None):
        if name not in NAMES:
            raise ValueError(name)
        self.name, self.model_dir, self.chronos_path = name, Path(model_dir), chronos_path

    def predict(self, bundle, fit_before):
        name = self.name
        details = {"method": name, "fit_before": fit_before}
        if name in ["cash", "SPY", "equal-weight"]:
            return Prediction("Sell" if name == "cash" else "Buy", None, {**details, "passive": True})
        dates, stock, bench = indices(bundle)
        returns = np.diff(np.log(stock)) - np.diff(np.log(bench))
        if name == "momentum-20":
            forecast = np.expm1(returns[-20:].sum() * 5 / 20)
        elif name == "mean-reversion-5":
            forecast = -np.expm1(returns[-5:].sum())
        elif name == "AR-5":
            # Fit a daily AR(5), recursively forecast six steps, exclude entry delay.
            eligible = returns[np.array(dates[1:]) < fit_before]
            x = np.array([eligible[i-5:i] for i in range(5, len(eligible))])
            coef = np.linalg.lstsq(np.c_[np.ones(len(x)), x], eligible[5:], rcond=None)[0]
            context, predicted = list(returns[-5:]), []
            for _ in range(6):
                value = float(np.dot([1, *context[-5:]], coef))
                predicted.append(value)
                context.append(value)
            forecast = np.expm1(sum(predicted[1:]))
            details.update(coefficients=coef.tolist(), training_observations=len(eligible), last_training_date=dates[len(eligible)])
        elif name == "chronos-bolt-small":
            if not self.chronos_path:
                raise ValueError("Download a pinned Chronos revision first and supply --chronos-path")
            import torch
            from chronos import BaseChronosPipeline
            pipeline = BaseChronosPipeline.from_pretrained(self.chronos_path, device_map="cpu", local_files_only=True)
            _, mean = pipeline.predict_quantiles(torch.tensor(np.stack([stock[-512:], bench[-512:]]), dtype=torch.float32),
                                                  prediction_length=6, quantile_levels=[.1, .5, .9])
            values = mean.numpy()
            forecast = values[0, 5] / values[0, 0] - values[1, 5] / values[1, 0]
            details.update(model_path=str(self.chronos_path), pretrained_contamination="unknown; retrospective", context_length=512)
        else:
            xt, yt, xv, yv, query, train = supervised(bundle, fit_before)
            details.update(train)
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler().fit(xt)
            xt, xv, query = [scaler.transform(a) for a in [xt, xv, query]]
            if name == "ridge":
                from sklearn.linear_model import Ridge
                model = Ridge(alpha=1.0).fit(xt, yt)
                forecast, validation = model.predict(query)[0], model.predict(xv)
                details["hyperparameters"] = {"alpha": 1.0}
            elif name == "XGBoost":
                from xgboost import XGBRegressor
                model = XGBRegressor(n_estimators=80, max_depth=3, learning_rate=.03, n_jobs=1, random_state=2026).fit(xt, yt)
                forecast, validation = model.predict(query)[0], model.predict(xv)
                details["hyperparameters"] = {"n_estimators": 80, "max_depth": 3, "learning_rate": .03, "seed": 2026}
            else:
                import torch
                from torch import nn
                torch.manual_seed(2026)
                torch.set_num_threads(1)
                # DLinear decomposition: moving trend + residual, two linear maps.
                class DLinear(nn.Module):
                    def __init__(self):
                        super().__init__()
                        self.trend = nn.Linear(20, 1)
                        self.seasonal = nn.Linear(20, 1)

                    def forward(self, x):
                        trend = nn.functional.avg_pool1d(nn.functional.pad(x[:, None], (2, 2), mode="replicate"), 5, stride=1)[:, 0]
                        return self.trend(trend) + self.seasonal(x - trend)
                model = DLinear()
                optim = torch.optim.Adam(model.parameters(), lr=.01)
                tx, ty = torch.tensor(xt, dtype=torch.float32), torch.tensor(yt[:, None], dtype=torch.float32)
                for _ in range(100):
                    optim.zero_grad()
                    loss = nn.functional.mse_loss(model(tx), ty)
                    loss.backward()
                    optim.step()
                with torch.no_grad():
                    forecast = model(torch.tensor(query, dtype=torch.float32)).item()
                    validation = model(torch.tensor(xv, dtype=torch.float32)).numpy()[:, 0]
                details["hyperparameters"] = {"lag": 20, "moving_average": 5, "epochs": 100, "lr": .01, "seed": 2026}
            details["validation_mae"] = float(np.abs(validation-yv).mean())
            self.model_dir.mkdir(parents=True, exist_ok=True)
            model_file = self.model_dir / (f'{bundle["case"]["cohort"]}-{bundle["case"]["ticker"]}-{name}')
            if name == "DLinear":
                torch.save({"weights": model.state_dict(), "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist()}, str(model_file) + ".pt")
            else:
                import joblib
                joblib.dump({"model": model, "scaler": scaler}, str(model_file) + ".joblib")
        if not np.isfinite(forecast):
            raise ValueError("Non-finite forecast")
        return Prediction(rating_for(float(forecast)), float(forecast), details)


def run_baselines(root, output, chronos_path=None):
    root, output = Path(root), Path(output)
    manifest = json.loads((root / "manifest.json").read_text())
    outcomes = json.loads((root / "outcomes.json").read_text())["cases"]
    start_by_cohort = {c["cohort"]: c["decision_date"] for c in cases() if c["side"] == "before"}
    rows = []
    for case_id, key in manifest["cases"].items():
        data = EvidenceStore(root).get(key)
        case = data["case"]
        for name in NAMES:
            path = output / "baselines" / case_id / (name + ".json")
            if path.exists():
                rows.append(json.loads(path.read_text()))
                continue
            started = time.monotonic()
            row = {**case, "phase": "campaign", "treatment": name, "trial": 0, "evidence_sha256": key,
                   "dataset_version": manifest["version"], "cost_upper_usd": 0.0, "cost_basis": "local inference; hardware cost unmetered"}
            try:
                result = NumericPredictor(name, output / "models", chronos_path).predict(data, start_by_cohort[case["cohort"]])
                row.update(asdict(result), status="success")
            except Exception as exc:
                row.update(status="failed", error=f"{type(exc).__name__}: {exc}", rating=None, forecast=None)
            row["latency_s"] = time.monotonic() - started
            row["scores_by_horizon"] = {h: score(row, value) for h, value in outcomes[case_id].items()}
            row["scores"] = row["scores_by_horizon"]["5"]
            # Passive methods are portfolio controls, not directional forecasts.
            if name in ["cash", "SPY", "equal-weight"]:
                for value in row["scores_by_horizon"].values():
                    value.update(directional_correct=None, signed_excess_return=None, absolute_forecast_error=None, actionable=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical(row))
            rows.append(row)
    return rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--chronos-path")
    args = parser.parse_args()
    rows = run_baselines(args.root, args.output, args.chronos_path)
    print(json.dumps({"predictions": len(rows), "failures": sum(r["status"] != "success" for r in rows)}))
