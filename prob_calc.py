import numpy as np
from scipy.stats import norm
import pandas as pd  # For nice table output (install if needed: pip3 install pandas)

def blended_prob(gut_score, historical_freq, iv_prob, gut_weight=0.6, hist_weight=0.2, iv_weight=0.2):
    """Hybrid blend: User-defined weights (defaults to 60/20/20 for balanced Burry)."""
    return (gut_weight * gut_score) + (hist_weight * historical_freq) + (iv_weight * iv_prob)

def calc_iv_prob(threshold, mean=0, sd=1):
    """Prob of drop > threshold using normal dist (NORM.CDF(-threshold/sd))."""
    return norm.cdf(-threshold / sd)  # Tail prob for downside

# Simple backtest sim: Dummy PYPL hist outcomes (e.g., past % returns post-earnings)
def quick_backtest(weights_list, scenarios):
    """Sim 'optimal' weights: Avg 'hit rate' on dummy hist (higher = better blend)."""
    dummy_hist_returns = np.array([-2.5, 1.2, -3.1, 5.0, -8.3])  # From our chat; expand w/ real data
    hit_rates = []
    for gw, hw, iw in weights_list:  # Test e.g., [80/10/10, 60/20/20]
        blended_probs = [blended_prob(s['gut_score'], s['hist_freq'], calc_iv_prob(s['threshold'], sd=s['sd']), gw, hw, iw) for s in scenarios.values()]
        # Mock 'hit': If blended < actual drop freq, count as win (simplified)
        mock_hits = sum(1 for i, p in enumerate(blended_probs) if p < abs(np.mean(dummy_hist_returns[i % len(dummy_hist_returns)]))/100)
        hit_rates.append(mock_hits / len(scenarios))
    best_idx = np.argmax(hit_rates)
    return weights_list[best_idx], hit_rates[best_idx]

# Example inputs for PYPL (gut defaults from before)
scenarios = {
    'Earnings Day 1 Drop >5%': {'gut_score': 0.7, 'hist_freq': 0.50, 'threshold': 5, 'sd': 8},
    'Earnings Day 1 Drop >10%': {'gut_score': 0.4, 'hist_freq': 0.30, 'threshold': 10, 'sd': 8},
    '1-Mo Pullback to $50': {'gut_score': 0.3, 'hist_freq': 0.20, 'threshold': 27.5, 'sd': 15}
}

# Backtest first: Test common weightings
test_weights = [(0.8, 0.1, 0.1), (0.6, 0.2, 0.2), (0.7, 0.15, 0.15)]
best_weights, best_hit = quick_backtest(test_weights, scenarios)
print(f"Quick Backtest: Best weights {best_weights} (hit rate: {best_hit:.0%})")

# Run calcs with best/default
results = []
for name, data in scenarios.items():
    iv_prob = calc_iv_prob(data['threshold'], sd=data['sd'])
    blended = blended_prob(data['gut_score'], data['hist_freq'], iv_prob, *best_weights)
    results.append({
        'Scenario': name,
        'Burry Gut Score': f"{data['gut_score']:.0%}",
        'Historical Freq': f"{data['hist_freq']:.0%}",
        'IV/Normal Prob': f"{iv_prob:.0%}",
        'Blended Prob': f"{blended:.0%}"
    })

# Display as table
df = pd.DataFrame(results)
print(df.to_string(index=False))

# Interactive: Custom weights + scenario
print("\n--- Custom Run ---")
custom_gw = float(input("Gut weight (0-1, e.g., 0.6): ") or 0.6)
custom_hw = float(input("Hist weight (0-1, e.g., 0.2): ") or 0.2)
custom_iw = float(input("IV weight (0-1, e.g., 0.2; must sum to 1): ") or 0.2)
if abs(custom_gw + custom_hw + custom_iw - 1) > 0.01:
    print("Warning: Weights don't sum to 1—adjusting proportionally.")
    total = custom_gw + custom_hw + custom_iw
    custom_gw, custom_hw, custom_iw = custom_gw/total, custom_hw/total, custom_iw/total

custom_gut = float(input("Burry Gut Score (0-1): "))
custom_hist = float(input("Historical freq (0-1): "))
custom_thresh = float(input("Threshold %: "))
custom_sd = float(input("SD %: "))
custom_iv = calc_iv_prob(custom_thresh, sd=custom_sd)
custom_blend = blended_prob(custom_gut, custom_hist, custom_iv, custom_gw, custom_hw, custom_iw)
print(f"\nCustom: Gut {custom_gut:.0%} + Hist {custom_hist:.0%} + IV {custom_iv:.0%} → Blended {custom_blend:.0%} (weights: {custom_gw:.0%}/{custom_hw:.0%}/{custom_iw:.0%})")
