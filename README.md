# FlowGenX - Unified Webhook Automation System

Enterprise-grade webhook receiver for Zendesk and HubSpot with comprehensive security, monitoring, and async processing.

## Project Structure

```
flowgenX/
├── backend/           # FastAPI backend
│   ├── api.py        # Main API endpoints
│   ├── requirements.txt
│   └── .venv/        # Python virtual environment
│
└── frontend/          # Next.js frontend
    ├── src/
    │   ├── app/      # Next.js app directory
    │   └── components/
    └── package.json
```

## Features

### Backend (FastAPI)
- ✅ Zendesk webhook integration
- ✅ HubSpot webhook integration
- ✅ HMAC signature verification
- ✅ Redis-based idempotency
- ✅ Circuit breaker pattern
- ✅ Async event processing
- ✅ 90+ Zendesk event types
- ✅ Comprehensive HubSpot events

### Frontend (Next.js + ShadCN)
- ✅ Modern API testing interface
- ✅ Test Zendesk connection
- ✅ Browse event categories
- ✅ View events by category
- ✅ Real-time response viewer
- ✅ Dark mode support

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Redis (optional, for production features)

### Backend Setup

1. Navigate to backend directory:
```powershell
cd backend
```

2. Create and activate virtual environment:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Install dependencies:
```powershell
pip install -r requirements.txt
```

4. Run the FastAPI server:
```powershell
python api.py
```

Backend will be available at: `http://localhost:5000`

### Frontend Setup

1. Navigate to frontend directory:
```powershell
cd frontend
```

2. Install dependencies:
```powershell
npm install
```

3. Run the development server:
```powershell
npm run dev
```

Frontend will be available at: `http://localhost:3000`

## API Endpoints

### Zendesk

#### Test Connection
```
POST /zendesk/test-connection
```
Test Zendesk API credentials.

**Request Body:**
```json
{
  "subdomain": "your-company",
  "email": "admin@company.com",
  "api_key": "your-api-key"
}
```

#### Get Event Categories
```
GET /zendesk/event-categories
```
Get all event categories with counts.

#### Get Events by Category
```
GET /zendesk/events/{category}
```
Get all events in a specific category.

**Categories:**
- `ticket` - Ticket lifecycle events
- `user` - User management events
- `organization` - Organization events
- `article` - Knowledge base events
- `community` - Community post events
- `agent_availability` - Agent status events

## Technology Stack

### Backend
- **FastAPI** - Modern Python web framework
- **Pydantic** - Data validation
- **Redis** - Idempotency and caching
- **Uvicorn** - ASGI server

### Frontend
- **Next.js 16** - React framework
- **React 19** - UI library
- **ShadCN UI** - Component library
- **Tailwind CSS v4** - Styling
- **TypeScript** - Type safety
- **Lucide React** - Icons

## Development

### Backend Development
```powershell
cd backend
python api.py
```

Access API docs at: `http://localhost:5000/docs`

### Frontend Development
```powershell
cd frontend
npm run dev
```

Access UI at: `http://localhost:3000`

## Environment Variables

### Backend
Create a `.env` file in the backend directory:
```env
REDIS_URL=redis://localhost:6379
ZENDESK_SIGNING_SECRET=your-secret
HUBSPOT_CLIENT_SECRET=your-secret
```

### Frontend
Create a `.env.local` file in the frontend directory:
```env
NEXT_PUBLIC_API_URL=http://localhost:5000
```

## Security Features

- ✅ HMAC SHA-256 signature verification
- ✅ Timestamp validation (5-minute window)
- ✅ Constant-time comparison (timing attack protection)
- ✅ Idempotency checks
- ✅ Circuit breaker for fault tolerance
- ✅ Rate limiting support

## License

MIT

## Author

Rakib - FlowGenX AI
