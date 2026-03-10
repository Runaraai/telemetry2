# Omniference Frontend

A modern React frontend for the Omniference hardware performance modeling and TCO analysis platform.

## Features

- **Profiling**: View and analyze benchmark profiling data
- **Manage Instances**: Manage cloud instances and run benchmarks
- **Real-time Results**: View performance, energy, and cost metrics
- **Modern UI**: Built with Material-UI for a clean, professional interface

## Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- Omniference backend running on http://localhost:8000

## Installation

1. Install dependencies:
```bash
npm install
```

2. Start the development server:
```bash
npm start
```

The app will open at http://localhost:3000

## Usage

### Profiling
- View profiling dashboard with benchmark data
- Analyze performance metrics and GPU utilization
- Compare different benchmark runs
- Explore detailed profiling results

### Manage Instances
- Manage cloud instances (Lambda Cloud, etc.)
- Setup and configure instances
- Run benchmarks on remote instances
- Monitor instance status and logs

## API Configuration

The frontend connects to the Omniference backend API. By default, it expects the backend to be running on `http://localhost:8000`.

To change the API URL, set the environment variable:
```bash
REACT_APP_API_URL=http://your-api-url:port
```

## Available Scripts

- `npm start` - Start development server
- `npm build` - Build for production
- `npm test` - Run tests
- `npm eject` - Eject from Create React App

## Project Structure

```
src/
├── components/          # Reusable UI components
│   ├── ProfilingDashboard.jsx    # Profiling dashboard component
│   └── SystemBenchmarkDashboard.jsx  # System benchmark dashboard
├── pages/              # Page components
│   ├── Benchmarking.js    # Profiling/Benchmarking page
│   └── ManageInstances.js # Instance management page
├── services/           # API services
│   └── api.js         # API client
├── App.js             # Main app component
└── index.js           # Entry point
```

## Technologies Used

- React 18
- Material-UI (MUI)
- React Router
- Axios for API calls
- Emotion for styling

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

ISC
