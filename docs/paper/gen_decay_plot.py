import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# Data
depths = np.array([0, 1, 2, 3, 4, 5])
step_thresholds = np.array([0.55, 0.55, 0.50, 0.50, 0.45, 0.45])
stage_labels = ["Atomics\n(d=0)", "BR\n(d=1)", "HLFR\n(d=2)", "LLFR\n(d=3)", "TR\n(d=4)", "TC\n(d=5)"]

# Exponential decay curve (smooth)
d_smooth = np.linspace(0, 5, 200)
tau_0 = 0.55
lam = 0.04
exp_decay = tau_0 * np.exp(-lam * d_smooth)

# Plot
fig, ax = plt.subplots(figsize=(7, 4))

# Exponential decay curve
ax.plot(d_smooth, exp_decay, 'b--', linewidth=1.5, alpha=0.7, 
        label=r'Exponential approximation: $\theta(d) \approx 0.55 \cdot e^{-0.04d}$')

# Step function (actual thresholds)
for i in range(len(depths)):
    x_start = depths[i] - 0.4 if i > 0 else 0
    x_end = depths[i] + 0.4 if i < len(depths)-1 else 5
    ax.plot([depths[i]-0.4, depths[i]+0.4], [step_thresholds[i], step_thresholds[i]], 
            'r-', linewidth=2.5, zorder=5)

# Scatter points
ax.scatter(depths, step_thresholds, color='red', s=80, zorder=6, edgecolors='darkred', linewidths=1.2,
           label=r'Step-function threshold $\theta(d)$')

# Gate B line
ax.axhline(y=0.7, color='green', linestyle=':', linewidth=1.2, alpha=0.5, label='Gate B threshold (score ≥ 7/10, normalized)')

# Annotations
for i, (d, th, label) in enumerate(zip(depths, step_thresholds, stage_labels)):
    ax.annotate(label, (d, th), textcoords="offset points", 
                xytext=(0, -22), ha='center', fontsize=7.5, color='#333333')

# Formatting
ax.set_xlabel('Tree Depth (d)', fontsize=11, fontweight='bold')
ax.set_ylabel('Gate A Threshold θ(d)', fontsize=11, fontweight='bold')
ax.set_title('Depth-Aware Threshold Degradation Schedule', fontsize=13, fontweight='bold')
ax.set_xlim(-0.5, 5.5)
ax.set_ylim(0.35, 0.75)
ax.set_xticks(depths)
ax.set_xticklabels([str(d) for d in depths])
ax.legend(loc='upper right', fontsize=8.5, framealpha=0.9)
ax.grid(True, alpha=0.3, linestyle='-')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

plt.tight_layout()
plt.savefig('threshold_decay.pdf', format='pdf', dpi=300, bbox_inches='tight')
print("Saved threshold_decay.pdf")
