"""
IEEE Publication-Quality Visualization for Edge Performance Paper

Generates figures formatted for IEEE two-column papers:
- Width: 3.5 inches (single column)
- Font: 8pt serif (Times New Roman compatible)
- Format: PDF for vector graphics

Figures generated:
- fig1-latency-boxplot.pdf: Latency distribution box plots
- fig2-latency-cdf.pdf: Cumulative distribution functions
- fig3-throughput-comparison.pdf: Throughput bar chart
- fig4-scenario-heatmap.pdf: Performance across scenarios

Usage:
    python visualize_paper.py [--input-dir benchmark/results] [--output-dir benchmark/analysis/figures]
"""

import json
import os
import glob
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy import stats

# ============================================================================
# IEEE Publication Style Configuration
# ============================================================================

# IEEE two-column format specifications
IEEE_COLUMN_WIDTH = 3.5  # inches
IEEE_FULL_WIDTH = 7.16   # inches (for two-column spanning figures)
GOLDEN_RATIO = 1.618

# Font sizes per IEEE guidelines
FONT_SIZE_SMALL = 7
FONT_SIZE_NORMAL = 8
FONT_SIZE_LARGE = 9

# Color palette - accessible and print-friendly
COLORS = {
    'cloudflare': '#E85D04',  # Orange (Cloudflare brand inspired)
    'vercel': '#171717',       # Near black (Vercel brand)
    'cloudflare_light': '#FAA307',
    'vercel_light': '#525252',
    'accent': '#0077B6',
    'grid': '#E5E5E5',
}

# Platform display names
PLATFORM_NAMES = {
    'cloudflare': 'Cloudflare Workers',
    'vercel': 'Vercel Edge',
}

def setup_ieee_style():
    """Configure matplotlib for IEEE publication quality."""
    plt.rcParams.update({
        # Font configuration
        'font.family': 'serif',
        'font.serif': ['Times New Roman', 'Times', 'DejaVu Serif'],
        'font.size': FONT_SIZE_NORMAL,
        
        # Axes
        'axes.labelsize': FONT_SIZE_NORMAL,
        'axes.titlesize': FONT_SIZE_LARGE,
        'axes.linewidth': 0.5,
        'axes.grid': True,
        'axes.axisbelow': True,
        
        # Ticks
        'xtick.labelsize': FONT_SIZE_SMALL,
        'ytick.labelsize': FONT_SIZE_SMALL,
        'xtick.major.width': 0.5,
        'ytick.major.width': 0.5,
        'xtick.major.size': 3,
        'ytick.major.size': 3,
        
        # Legend
        'legend.fontsize': FONT_SIZE_SMALL,
        'legend.frameon': True,
        'legend.framealpha': 0.9,
        'legend.edgecolor': 'gray',
        
        # Figure
        'figure.dpi': 300,
        'figure.figsize': (IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH / GOLDEN_RATIO),
        
        # Saving
        'savefig.dpi': 300,
        'savefig.bbox': 'tight',
        'savefig.pad_inches': 0.02,
        
        # Grid
        'grid.linewidth': 0.3,
        'grid.alpha': 0.5,
        'grid.color': COLORS['grid'],
        
        # Lines
        'lines.linewidth': 1.0,
        'lines.markersize': 4,
    })


# ============================================================================
# Data Loading Functions
# ============================================================================

def load_benchmark_results(input_dir: str) -> Dict[str, Dict[str, List[Dict]]]:
    """Load benchmark results organized by scenario and platform."""
    results = {
        'warm-performance': {'cloudflare': [], 'vercel': []},
        'load-test': {'cloudflare': [], 'vercel': []},
        'burst-test': {'cloudflare': [], 'vercel': []},
    }
    
    json_files = glob.glob(os.path.join(input_dir, '*.json'))
    
    for file_path in json_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            filename = os.path.basename(file_path).lower()
            
            # Skip aggregated/summary files
            if 'aggregated' in filename or 'summary' in filename:
                continue
            
            # Determine platform
            platform = None
            if 'cloudflare' in filename:
                platform = 'cloudflare'
            elif 'vercel' in filename:
                platform = 'vercel'
            
            if not platform:
                continue
            
            # Determine scenario
            for scenario in results.keys():
                if scenario in filename:
                    data['_filename'] = filename
                    data['_platform'] = platform
                    results[scenario][platform].append(data)
                    break
                    
        except Exception as e:
            print(f"Warning: Failed to load {file_path}: {e}")
    
    return results


def extract_metrics_df(results: Dict[str, Dict[str, List[Dict]]]) -> pd.DataFrame:
    """Extract all metrics into a single DataFrame for analysis."""
    rows = []
    
    for scenario, platforms in results.items():
        for platform, runs in platforms.items():
            for run_idx, data in enumerate(runs):
                if 'metrics' not in data:
                    continue
                
                metrics = data['metrics']
                row = {
                    'scenario': scenario,
                    'platform': platform,
                    'platform_name': PLATFORM_NAMES.get(platform, platform),
                    'run': run_idx + 1,
                }
                
                # HTTP request duration metrics
                if 'http_req_duration' in metrics:
                    dur = metrics['http_req_duration'].get('values', {})
                    row['latency_avg'] = dur.get('avg')
                    row['latency_min'] = dur.get('min')
                    row['latency_max'] = dur.get('max')
                    row['latency_med'] = dur.get('med')
                    row['latency_p90'] = dur.get('p(90)')
                    row['latency_p95'] = dur.get('p(95)')
                    row['latency_p99'] = dur.get('p(99)')
                
                # Request count and throughput
                if 'http_reqs' in metrics:
                    reqs = metrics['http_reqs'].get('values', {})
                    row['total_requests'] = reqs.get('count')
                    row['throughput'] = reqs.get('rate')
                
                # Error rate
                if 'http_req_failed' in metrics:
                    failed = metrics['http_req_failed'].get('values', {})
                    row['error_rate'] = failed.get('rate', 0) * 100
                
                rows.append(row)
    
    return pd.DataFrame(rows)


# ============================================================================
# Figure Generation Functions
# ============================================================================

def create_latency_boxplot(df: pd.DataFrame, output_dir: str) -> str:
    """
    Create box plot comparing latency distributions.
    
    Figure 1: Latency Distribution Comparison
    Shows P50, P95, P99 for each platform across scenarios.
    """
    setup_ieee_style()
    
    fig, ax = plt.subplots(figsize=(IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH * 0.75))
    
    # Filter to warm-performance for cleaner comparison
    warm_df = df[df['scenario'] == 'warm-performance'].copy()
    
    if warm_df.empty:
        print("No warm-performance data for box plot")
        plt.close()
        return ""
    
    # Prepare data for box plot
    cf_data = warm_df[warm_df['platform'] == 'cloudflare']
    vercel_data = warm_df[warm_df['platform'] == 'vercel']
    
    # Create synthetic distributions from percentiles (for visualization)
    # In real scenario, we'd use raw latency data
    positions = [1, 2]
    box_data = []
    
    for data, platform in [(cf_data, 'cloudflare'), (vercel_data, 'vercel')]:
        if not data.empty:
            # Use actual run averages as data points
            values = data['latency_avg'].dropna().values
            box_data.append(values)
        else:
            box_data.append([0])
    
    # Create box plot
    bp = ax.boxplot(box_data, positions=positions, widths=0.5, patch_artist=True,
                    medianprops=dict(color='white', linewidth=1.5),
                    whiskerprops=dict(linewidth=0.8),
                    capprops=dict(linewidth=0.8),
                    flierprops=dict(marker='o', markersize=3))
    
    # Color boxes
    colors = [COLORS['cloudflare'], COLORS['vercel']]
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)
    
    # Add individual data points (jittered)
    for i, (data, pos) in enumerate([(cf_data, 1), (vercel_data, 2)]):
        if not data.empty:
            y = data['latency_avg'].dropna().values
            x = np.random.normal(pos, 0.04, size=len(y))
            ax.scatter(x, y, alpha=0.6, s=20, color='white', edgecolors='black', linewidth=0.5, zorder=3)
    
    # Labels and formatting
    ax.set_xticklabels(['Cloudflare\nWorkers', 'Vercel\nEdge'])
    ax.set_ylabel('Average Latency (ms)')
    ax.set_title('Warm Latency Distribution')
    
    # Add mean values as text
    for i, data in enumerate([cf_data, vercel_data]):
        if not data.empty:
            mean_val = data['latency_avg'].mean()
            ax.annotate(f'{mean_val:.1f}ms', 
                       xy=(i+1, mean_val),
                       xytext=(i+1+0.35, mean_val),
                       fontsize=FONT_SIZE_SMALL,
                       va='center')
    
    ax.set_ylim(bottom=0)
    plt.tight_layout()
    
    # Save
    output_path = os.path.join(output_dir, 'fig1-latency-boxplot.pdf')
    plt.savefig(output_path, format='pdf')
    plt.savefig(output_path.replace('.pdf', '.png'), format='png', dpi=300)
    plt.close()
    
    print(f"Saved: {output_path}")
    return output_path


def create_latency_cdf(df: pd.DataFrame, output_dir: str) -> str:
    """
    Create CDF plot of latency distributions.
    
    Figure 2: Cumulative Distribution Function
    Shows full latency distribution for each platform.
    """
    setup_ieee_style()
    
    fig, ax = plt.subplots(figsize=(IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH * 0.75))
    
    # Get warm-performance data
    warm_df = df[df['scenario'] == 'warm-performance'].copy()
    
    if warm_df.empty:
        print("No warm-performance data for CDF")
        plt.close()
        return ""
    
    # Since we don't have raw latency data, create synthetic CDFs from percentiles
    for platform, color, label in [
        ('cloudflare', COLORS['cloudflare'], 'Cloudflare Workers'),
        ('vercel', COLORS['vercel'], 'Vercel Edge')
    ]:
        platform_df = warm_df[warm_df['platform'] == platform]
        if platform_df.empty:
            continue
        
        # Get average percentile values across runs
        p_values = {
            0: platform_df['latency_min'].mean(),
            50: platform_df['latency_med'].mean() if 'latency_med' in platform_df else platform_df['latency_avg'].mean(),
            90: platform_df['latency_p90'].mean(),
            95: platform_df['latency_p95'].mean(),
            99: platform_df['latency_p99'].mean() if 'latency_p99' in platform_df else platform_df['latency_max'].mean(),
            100: platform_df['latency_max'].mean(),
        }
        
        # Create smooth CDF using interpolation
        percentiles = sorted(p_values.keys())
        latencies = [p_values[p] for p in percentiles]
        
        # Interpolate for smoother curve
        interp_percentiles = np.linspace(0, 100, 100)
        interp_latencies = np.interp(interp_percentiles, percentiles, latencies)
        
        ax.plot(interp_latencies, interp_percentiles / 100, 
                color=color, linewidth=1.5, label=label)
        
        # Add P95 marker
        p95_lat = p_values.get(95, 0)
        ax.scatter([p95_lat], [0.95], color=color, s=30, zorder=5, marker='o')
        ax.annotate(f'P95: {p95_lat:.0f}ms', 
                   xy=(p95_lat, 0.95),
                   xytext=(p95_lat + 5, 0.90),
                   fontsize=FONT_SIZE_SMALL,
                   color=color)
    
    ax.set_xlabel('Latency (ms)')
    ax.set_ylabel('Cumulative Probability')
    ax.set_title('Latency CDF Comparison')
    ax.legend(loc='lower right')
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)
    
    # Add P95 reference line
    ax.axhline(y=0.95, color='gray', linestyle='--', linewidth=0.5, alpha=0.7)
    ax.text(ax.get_xlim()[1] * 0.02, 0.96, 'P95', fontsize=FONT_SIZE_SMALL, color='gray')
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'fig2-latency-cdf.pdf')
    plt.savefig(output_path, format='pdf')
    plt.savefig(output_path.replace('.pdf', '.png'), format='png', dpi=300)
    plt.close()
    
    print(f"Saved: {output_path}")
    return output_path


def create_throughput_comparison(df: pd.DataFrame, output_dir: str) -> str:
    """
    Create throughput comparison bar chart.
    
    Figure 3: Throughput Under Load
    Shows requests/second for each platform.
    """
    setup_ieee_style()
    
    fig, ax = plt.subplots(figsize=(IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH * 0.65))
    
    # Get load-test data
    load_df = df[df['scenario'] == 'load-test'].copy()
    
    if load_df.empty:
        print("No load-test data for throughput comparison")
        plt.close()
        return ""
    
    # Calculate mean and std for each platform
    stats_data = load_df.groupby('platform').agg({
        'throughput': ['mean', 'std', 'count']
    }).reset_index()
    stats_data.columns = ['platform', 'mean', 'std', 'count']
    
    # Order platforms
    platform_order = ['cloudflare', 'vercel']
    stats_data['order'] = stats_data['platform'].map({p: i for i, p in enumerate(platform_order)})
    stats_data = stats_data.sort_values('order')
    
    # Create bars
    x = np.arange(len(stats_data))
    colors = [COLORS[p] for p in stats_data['platform']]
    
    bars = ax.bar(x, stats_data['mean'], 
                  yerr=stats_data['std'],
                  color=colors,
                  edgecolor='black',
                  linewidth=0.5,
                  capsize=3,
                  error_kw={'linewidth': 0.8})
    
    # Add value labels on bars
    for bar, mean_val in zip(bars, stats_data['mean']):
        height = bar.get_height()
        ax.annotate(f'{mean_val:.1f}',
                   xy=(bar.get_x() + bar.get_width() / 2, height),
                   xytext=(0, 3),
                   textcoords="offset points",
                   ha='center', va='bottom',
                   fontsize=FONT_SIZE_NORMAL,
                   fontweight='bold')
    
    # Labels
    ax.set_xticks(x)
    ax.set_xticklabels([PLATFORM_NAMES[p] for p in stats_data['platform']])
    ax.set_ylabel('Throughput (req/s)')
    ax.set_title('Throughput Under Load (10 VUs)')
    
    # Calculate and display improvement
    cf_mean = stats_data[stats_data['platform'] == 'cloudflare']['mean'].values[0]
    vercel_mean = stats_data[stats_data['platform'] == 'vercel']['mean'].values[0]
    if vercel_mean > 0:
        improvement = ((cf_mean - vercel_mean) / vercel_mean) * 100
        ax.text(0.5, 0.95, f'CF {improvement:.0f}% higher throughput',
               transform=ax.transAxes,
               ha='center', va='top',
               fontsize=FONT_SIZE_SMALL,
               style='italic',
               color='gray')
    
    ax.set_ylim(bottom=0)
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'fig3-throughput-comparison.pdf')
    plt.savefig(output_path, format='pdf')
    plt.savefig(output_path.replace('.pdf', '.png'), format='png', dpi=300)
    plt.close()
    
    print(f"Saved: {output_path}")
    return output_path


def create_percentile_comparison(df: pd.DataFrame, output_dir: str) -> str:
    """
    Create multi-scenario percentile comparison.
    
    Figure 4: Latency Percentiles Across Scenarios
    Grouped bar chart showing P50, P95, P99 for each platform/scenario.
    """
    setup_ieee_style()
    
    fig, ax = plt.subplots(figsize=(IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH * 0.8))
    
    # Aggregate data by scenario and platform
    agg_df = df.groupby(['scenario', 'platform']).agg({
        'latency_avg': 'mean',
        'latency_p95': 'mean',
    }).reset_index()
    
    if agg_df.empty:
        print("No data for percentile comparison")
        plt.close()
        return ""
    
    # Setup bar positions
    scenarios = ['warm-performance', 'load-test', 'burst-test']
    scenario_labels = ['Warm', 'Load\n(10 VUs)', 'Burst\n(100 VUs)']
    x = np.arange(len(scenarios))
    width = 0.35
    
    # Extract data for each platform
    cf_avg = []
    cf_p95 = []
    vercel_avg = []
    vercel_p95 = []
    
    for scenario in scenarios:
        cf_data = agg_df[(agg_df['scenario'] == scenario) & (agg_df['platform'] == 'cloudflare')]
        vercel_data = agg_df[(agg_df['scenario'] == scenario) & (agg_df['platform'] == 'vercel')]
        
        cf_avg.append(cf_data['latency_avg'].values[0] if not cf_data.empty else 0)
        cf_p95.append(cf_data['latency_p95'].values[0] if not cf_data.empty else 0)
        vercel_avg.append(vercel_data['latency_avg'].values[0] if not vercel_data.empty else 0)
        vercel_p95.append(vercel_data['latency_p95'].values[0] if not vercel_data.empty else 0)
    
    # Create grouped bars
    bars1 = ax.bar(x - width/2, cf_p95, width, label='Cloudflare P95',
                   color=COLORS['cloudflare'], edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x + width/2, vercel_p95, width, label='Vercel P95',
                   color=COLORS['vercel'], edgecolor='black', linewidth=0.5)
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.annotate(f'{height:.0f}',
                           xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 2),
                           textcoords="offset points",
                           ha='center', va='bottom',
                           fontsize=FONT_SIZE_SMALL)
    
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_labels)
    ax.set_ylabel('P95 Latency (ms)')
    ax.set_title('P95 Latency Across Scenarios')
    ax.legend(loc='upper left', fontsize=FONT_SIZE_SMALL)
    ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'fig4-percentile-comparison.pdf')
    plt.savefig(output_path, format='pdf')
    plt.savefig(output_path.replace('.pdf', '.png'), format='png', dpi=300)
    plt.close()
    
    print(f"Saved: {output_path}")
    return output_path


def create_summary_table_figure(df: pd.DataFrame, output_dir: str) -> str:
    """
    Create a table figure summarizing key metrics.
    
    Figure 5: Summary Statistics Table (as figure)
    """
    setup_ieee_style()
    
    fig, ax = plt.subplots(figsize=(IEEE_COLUMN_WIDTH, IEEE_COLUMN_WIDTH * 0.5))
    ax.axis('off')
    
    # Calculate summary statistics
    summary_data = []
    for scenario in ['warm-performance', 'load-test', 'burst-test']:
        scenario_df = df[df['scenario'] == scenario]
        for platform in ['cloudflare', 'vercel']:
            platform_df = scenario_df[scenario_df['platform'] == platform]
            if not platform_df.empty:
                summary_data.append({
                    'Scenario': scenario.replace('-', ' ').title(),
                    'Platform': PLATFORM_NAMES[platform],
                    'Avg (ms)': f"{platform_df['latency_avg'].mean():.1f}",
                    'P95 (ms)': f"{platform_df['latency_p95'].mean():.1f}",
                    'Throughput': f"{platform_df['throughput'].mean():.1f}" if not platform_df['throughput'].isna().all() else 'N/A'
                })
    
    summary_df = pd.DataFrame(summary_data)
    
    if summary_df.empty:
        plt.close()
        return ""
    
    # Create table
    table = ax.table(
        cellText=summary_df.values,
        colLabels=summary_df.columns,
        loc='center',
        cellLoc='center',
        colColours=['#f0f0f0'] * len(summary_df.columns)
    )
    table.auto_set_font_size(False)
    table.set_fontsize(FONT_SIZE_SMALL)
    table.scale(1.2, 1.5)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'fig5-summary-table.pdf')
    plt.savefig(output_path, format='pdf')
    plt.savefig(output_path.replace('.pdf', '.png'), format='png', dpi=300)
    plt.close()
    
    print(f"Saved: {output_path}")
    return output_path


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate IEEE publication-quality figures'
    )
    parser.add_argument('--input-dir', default='benchmark/results',
                        help='Directory containing benchmark JSON files')
    parser.add_argument('--output-dir', default='benchmark/analysis/figures',
                        help='Directory for output figures')
    
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("=" * 60)
    print("IEEE Publication-Quality Figure Generator")
    print("=" * 60)
    print(f"Input directory: {args.input_dir}")
    print(f"Output directory: {args.output_dir}")
    
    # Load data
    print("\nLoading benchmark results...")
    results = load_benchmark_results(args.input_dir)
    
    # Count loaded files
    total = sum(len(results[s][p]) for s in results for p in results[s])
    print(f"Loaded {total} result files")
    
    for scenario in results:
        cf_n = len(results[scenario]['cloudflare'])
        vercel_n = len(results[scenario]['vercel'])
        if cf_n > 0 or vercel_n > 0:
            print(f"  {scenario}: CF={cf_n}, Vercel={vercel_n}")
    
    if total == 0:
        print("\nNo benchmark results found. Run benchmarks first.")
        return
    
    # Extract to DataFrame
    df = extract_metrics_df(results)
    print(f"\nExtracted {len(df)} data points")
    
    # Generate figures
    print("\n" + "-" * 40)
    print("Generating IEEE figures...")
    print("-" * 40)
    
    generated_files = []
    
    # Figure 1: Box plot
    path = create_latency_boxplot(df, args.output_dir)
    if path:
        generated_files.append(path)
    
    # Figure 2: CDF
    path = create_latency_cdf(df, args.output_dir)
    if path:
        generated_files.append(path)
    
    # Figure 3: Throughput
    path = create_throughput_comparison(df, args.output_dir)
    if path:
        generated_files.append(path)
    
    # Figure 4: Percentile comparison
    path = create_percentile_comparison(df, args.output_dir)
    if path:
        generated_files.append(path)
    
    # Figure 5: Summary table
    path = create_summary_table_figure(df, args.output_dir)
    if path:
        generated_files.append(path)
    
    print("\n" + "=" * 60)
    print("FIGURE GENERATION COMPLETE")
    print("=" * 60)
    print(f"Generated {len(generated_files)} figures:")
    for f in generated_files:
        print(f"  - {os.path.basename(f)}")
    print(f"\nOutput directory: {args.output_dir}")


if __name__ == '__main__':
    main()
