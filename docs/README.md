# MemGUI-Bench GitHub Pages

This is the official project page for **MemGUI-Bench: Benchmarking Memory of Mobile GUI Agents in Dynamic Environments**.
The root landing page uses the MobileWorld-style Bulma layout shared with
`site/`, while the detailed leaderboard and submission pages remain available as
supporting pages.

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
docs/
├── index.html              # MobileWorld-style landing page
├── style.css               # MobileWorld-style landing page styles
├── leaderboard.json        # Landing page leaderboard data
├── leaderboard.html        # Detailed leaderboard page
├── submission.html         # Submission guidelines
├── eval-pipeline.html      # Evaluation details
├── failure-analysis.html   # Failure analysis details
├── assets/                 # Landing page assets
├── css/                    # Supporting page styles
├── js/                     # Supporting page scripts
├── data/                   # Supporting page data
└── images/                 # Paper figures
```

## 📊 Leaderboard Management

### Adding New Results

1. Edit `leaderboard.json` for the landing page, or `data/index.json` for the detailed pages
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

Edit CSS variables in `style.css` for the landing page. Supporting pages use
their files under `css/`.

```css
:root {
  --primary: #6366f1;        /* Primary accent color */
  --accent: #22d3ee;         /* Secondary accent */
  --bg-dark: #0f0f1a;        /* Background color */
  /* ... */
}
```

## 📧 Contact

For questions about the benchmark or leaderboard submissions, please contact: **guangyiliu@zju.edu.cn**.

## 📜 License

MIT License - See LICENSE file for details.
