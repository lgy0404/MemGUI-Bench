# MemGUI-Bench GitHub Pages

This is the official project page for **MemGUI-Bench: Benchmarking Memory of Mobile GUI Agents in Dynamic Environments**.

## 🚀 Quick Start

### Local Development

```bash
# Simply open index.html in a browser
# Or use a local server:
python -m http.server 8000
# Then visit http://localhost:8000
```

### Deployment

This site is designed for GitHub Pages. Simply:
1. Push to the `gh-pages` branch, or
2. Configure GitHub Pages in repository settings to serve from the `main` branch

## 📁 Project Structure

```
memgui-bench-gh-page/
├── index.html              # Main landing page
├── leaderboard.html        # Results leaderboard
├── submission.html         # Submission guidelines
├── css/
│   ├── style.css           # Global styles
│   ├── leaderboard.css     # Leaderboard-specific styles
│   └── submission.css      # Submission page styles
├── js/
│   └── leaderboard.js      # Leaderboard functionality
├── data/
│   └── results.json        # Leaderboard data
├── assets/
│   └── favicon.png         # Site favicon
└── README.md
```

## 📊 Leaderboard Management

### Adding New Results

1. Edit `data/results.json`
2. Add a new agent entry following the existing format:

```json
{
  "name": "YourAgent",
  "type": "Agentic Workflow",
  "link": "https://github.com/...",
  "hasLongTermMemory": true,
  "shortTerm": {
    "easy": 41.7,
    "medium": 19.0,
    "hard": 18.4,
    "overall": 27.3,
    "irr": 39.5,
    "mtpr": 0.45,
    "timePerStep": 28.1,
    "costPerStep": 0.051
  },
  "longTerm": {
    "easy": 64.6,
    "medium": 42.9,
    "hard": 36.8,
    "overall": 49.2,
    "frr": 21.5,
    "improvement": 21.9
  }
}
```

### Metrics Explained

#### Short-Term Memory (pass@1)
- **SR (Success Rate)**: Percentage of tasks completed successfully
- **IRR (Information Retention Rate)**: Memory fidelity metric
- **MTPR (Memory-Task Proficiency Ratio)**: Memory-specific capability

#### Long-Term Memory (pass@k)
- **SR@k**: Multi-attempt success rate
- **FRR (Failure Recovery Rate)**: Learning from failure efficiency
- **Improvement**: Performance gain from pass@1 to pass@k

## 🔧 Customization

### Updating Links

1. **Paper Link**: Update in `index.html` hero buttons
2. **GitHub Link**: Update in `index.html` and navigation
3. **Dataset Link**: Update in `index.html` hero buttons

### Changing Colors

Edit CSS variables in `css/style.css`:

```css
:root {
  --primary: #6366f1;        /* Primary accent color */
  --accent: #22d3ee;         /* Secondary accent */
  --bg-dark: #0f0f1a;        /* Background color */
  /* ... */
}
```

## 📧 Contact

For questions about the benchmark or leaderboard submissions, please contact: memgui-bench@example.com

## 📜 License

MIT License - See LICENSE file for details.

