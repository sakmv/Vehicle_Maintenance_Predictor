"""
Generates a synthetic but realistic vehicle sensor dataset for predictive maintenance.

Failure probability is driven by a weighted combination of sensor readings so the
model learns genuine, explainable relationships (not random noise).
"""
import numpy as np
import pandas as pd

np.random.seed(42)
N = 15000

def generate():
    mileage = np.random.gamma(shape=2.0, scale=35000, size=N).clip(500, 300000)
    vehicle_age_years = (mileage / 15000) + np.random.normal(0, 0.8, N)
    vehicle_age_years = vehicle_age_years.clip(0.2, 20)

    engine_temp = np.random.normal(90, 12, N).clip(60, 140)
    rpm = np.random.normal(2200, 700, N).clip(600, 7000)
    vibration = np.random.gamma(shape=1.5, scale=0.03, size=N).clip(0.001, 1.2)
    oil_quality_pct = (100 - (mileage / 4000)).clip(0, 100) + np.random.normal(0, 8, N)
    oil_quality_pct = oil_quality_pct.clip(0, 100)
    brake_pad_mm = (12 - (mileage / 20000)).clip(0.5, 12) + np.random.normal(0, 1.0, N)
    brake_pad_mm = brake_pad_mm.clip(0.5, 12)
    battery_voltage = np.random.normal(12.6, 0.6, N).clip(9.5, 14.5) - (vehicle_age_years * 0.03)
    coolant_level_pct = np.random.normal(85, 15, N).clip(0, 100)

    # Weighted risk score built from domain-plausible thresholds
    risk = np.zeros(N)
    risk += np.clip((mileage - 80000) / 100000, 0, 1) * 1.5
    risk += np.clip((engine_temp - 100) / 30, 0, 1) * 2.0
    risk += np.clip((vibration - 0.15) / 0.5, 0, 1) * 2.5
    risk += np.clip((30 - oil_quality_pct) / 30, 0, 1) * 1.8
    risk += np.clip((3 - brake_pad_mm) / 3, 0, 1) * 2.2
    risk += np.clip((11.8 - battery_voltage) / 2, 0, 1) * 1.2
    risk += np.clip((50 - coolant_level_pct) / 50, 0, 1) * 1.0
    risk += np.clip((rpm - 4500) / 2000, 0, 1) * 0.8

    risk += np.random.normal(0, 0.15, N)  # noise
    prob = 1 / (1 + np.exp(-(risk - 2.7) * 1.6))  # sigmoid -> probability, sharper
    failure = (np.random.rand(N) < prob).astype(int)

    df = pd.DataFrame({
        "mileage_km": mileage.round(0),
        "engine_temp_c": engine_temp.round(1),
        "rpm": rpm.round(0),
        "vibration_level": vibration.round(4),
        "oil_quality_pct": oil_quality_pct.round(1),
        "brake_pad_mm": brake_pad_mm.round(2),
        "battery_voltage": battery_voltage.round(2),
        "coolant_level_pct": coolant_level_pct.round(1),
        "vehicle_age_years": vehicle_age_years.round(1),
        "failure_risk": failure,
    })
    return df

if __name__ == "__main__":
    df = generate()
    df.to_csv("sensor_data.csv", index=False)
    print(df["failure_risk"].value_counts(normalize=True))
    print(df.describe())
