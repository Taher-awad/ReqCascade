import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ============================================================
# Chart 1: Per-Stage Gate Pass Rate
# ============================================================
stages = ['Atomics', 'BR', 'HLFR', 'LLFR', 'TR', 'TC']
pass_rates = [100, 100, 100, 100, 75, 25]
colors = ['#2ecc71' if r == 100 else '#e67e22' if r >= 50 else '#e74c3c' for r in pass_rates]

fig1, ax1 = plt.subplots(figsize=(7, 4))
bars = ax1.bar(stages, pass_rates, color=colors, edgecolor='#2c3e50', linewidth=0.8, width=0.6)
ax1.axhline(y=75, color='#3498db', linestyle='--', linewidth=1.5, alpha=0.8, label='Overall pass rate (75%)')

# Value labels on bars
for bar, val in zip(bars, pass_rates):
    ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 2, 
             f'{val}%', ha='center', va='bottom', fontweight='bold', fontsize=10)

ax1.set_xlabel('Pipeline Stage', fontsize=11, fontweight='bold')
ax1.set_ylabel('Gate Pass Rate (%)', fontsize=11, fontweight='bold')
ax1.set_title('Dual-Gate Validation Pass Rate by Pipeline Stage', fontsize=13, fontweight='bold')
ax1.set_ylim(0, 115)
ax1.legend(loc='lower left', fontsize=9, framealpha=0.9)
ax1.grid(axis='y', alpha=0.3, linestyle='-')
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)

plt.tight_layout()
plt.savefig('passrate_chart.pdf', format='pdf', dpi=300, bbox_inches='tight')
print("Saved passrate_chart.pdf")
plt.close()

# ============================================================
# Chart 2: LLM Call Count Comparison
# ============================================================
categories = ['Pruned\n(This Work)', 'Full Tree\n(No Pruning)', 'Worst Case\n(All Retries)']
gen_calls = [16, 64, 64*4]
critic_calls = [15, 60, 60*4]

fig2, ax2 = plt.subplots(figsize=(7, 4))
x = np.arange(len(categories))
width = 0.32

bars1 = ax2.bar(x - width/2, gen_calls, width, label='Generation Calls', 
                color='#3498db', edgecolor='#2c3e50', linewidth=0.8)
bars2 = ax2.bar(x + width/2, critic_calls, width, label='Critic Calls', 
                color='#e74c3c', edgecolor='#2c3e50', linewidth=0.8)

# Value labels
for bar in bars1:
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 5,
             str(int(bar.get_height())), ha='center', va='bottom', fontsize=9, fontweight='bold')
for bar in bars2:
    ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 5,
             str(int(bar.get_height())), ha='center', va='bottom', fontsize=9, fontweight='bold')

# Total labels
totals = [31, 124, 496]
for i, total in enumerate(totals):
    ax2.text(x[i], max(gen_calls[i], critic_calls[i]) + 25,
             f'Total: {total}', ha='center', va='bottom', fontsize=10, fontweight='bold',
             color='#2c3e50', bbox=dict(boxstyle='round,pad=0.3', facecolor='#f0f0f0', edgecolor='#bdc3c7'))

ax2.set_xlabel('Execution Mode', fontsize=11, fontweight='bold')
ax2.set_ylabel('Number of LLM API Calls', fontsize=11, fontweight='bold')
ax2.set_title('Computational Cost: LLM Call Count by Execution Mode', fontsize=13, fontweight='bold')
ax2.set_xticks(x)
ax2.set_xticklabels(categories)
ax2.legend(loc='upper left', fontsize=9, framealpha=0.9)
ax2.grid(axis='y', alpha=0.3, linestyle='-')
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)
ax2.set_ylim(0, max(max(gen_calls), max(critic_calls)) + 60)

plt.tight_layout()
plt.savefig('llmcalls_chart.pdf', format='pdf', dpi=300, bbox_inches='tight')
print("Saved llmcalls_chart.pdf")
plt.close()
