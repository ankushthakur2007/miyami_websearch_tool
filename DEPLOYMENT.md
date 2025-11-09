# Deploy to Railway - Step by Step Guide

## Prerequisites

1. **Sign up for Railway**
   - Go to [Railway.app](https://railway.app)
   - Sign up with GitHub (recommended) or email
   - No CLI installation needed!

## Deployment Steps

### Method 1: Deploy from GitHub (Recommended)

#### Step 1: Push Your Code to GitHub

If not already on GitHub:
```bash
cd /Users/ankushthakur/miyami_search_api
git init
git add .
git commit -m "Initial commit for Railway deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

#### Step 2: Deploy on Railway

1. Go to [Railway.app](https://railway.app)
2. Click "Start a New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub
5. Select your repository
6. Railway will automatically detect the Dockerfile and deploy

#### Step 3: Configure Environment Variables

In the Railway dashboard:
1. Go to your project
2. Click on "Variables" tab
3. Add the following variables:
   ```
   SEARXNG_SECRET = (generate with: openssl rand -hex 32)
   SEARXNG_DEBUG = 0
   SEARXNG_BIND_ADDRESS = 127.0.0.1:8888
   PORT = 8080
   ```

#### Step 4: Get Your Domain

1. In Railway dashboard, go to "Settings" tab
2. Under "Domains" section, click "Generate Domain"
3. Your app will be available at: `https://your-app-name.up.railway.app`

### Method 2: Deploy with Railway CLI

#### Step 1: Install Railway CLI

```bash
# macOS/Linux
npm i -g @railway/cli

# Or with Homebrew
brew install railway
```

#### Step 2: Login

```bash
railway login
```

#### Step 3: Initialize and Deploy

```bash
cd /Users/ankushthakur/miyami_search_api

# Initialize Railway project
railway init

# Set environment variables
railway variables set SEARXNG_SECRET=$(openssl rand -hex 32)
railway variables set SEARXNG_DEBUG=0
railway variables set SEARXNG_BIND_ADDRESS="127.0.0.1:8888"
railway variables set PORT=8080

# Deploy
railway up
```

#### Step 4: Open Your App

```bash
railway open
```

## Testing Your Deployment

Once deployed, your API will be available at: `https://your-app-name.up.railway.app`

Test the endpoints:

1. **Health Check**
   ```bash
   curl https://your-app-name.up.railway.app/health
   ```

2. **Search API**
   ```bash
   curl "https://your-app-name.up.railway.app/search-api?query=weather"
   ```

3. **Fetch API**
   ```bash
   curl "https://your-app-name.up.railway.app/fetch?url=https://example.com"
   ```

4. **API Documentation**
   - Swagger UI: `https://your-app-name.up.railway.app/docs`
   - ReDoc: `https://your-app-name.up.railway.app/redoc`

## Monitoring & Logs

### In Railway Dashboard:
1. Go to your project
2. Click on "Deployments" tab to see deployment history
3. Click on "Logs" tab to view real-time logs
4. Click on "Metrics" tab to see CPU, Memory, and Network usage

### With Railway CLI:
```bash
# View real-time logs
railway logs

# View logs with follow
railway logs --follow
```

## Updating Your App

### From GitHub (Automatic):
- Simply push to your main branch
- Railway automatically detects changes and redeploys

### With Railway CLI:
```bash
# After making changes
railway up

# Or if linked to GitHub, just push
git add .
git commit -m "Update"
git push
```

## Environment Variables

Set these in Railway dashboard or CLI:

| Variable | Value | Description |
|----------|-------|-------------|
| SEARXNG_SECRET | (random 32-byte hex) | Secret key for SearXNG |
| SEARXNG_DEBUG | 0 | Debug mode (0 for production) |
| SEARXNG_BIND_ADDRESS | 127.0.0.1:8888 | SearXNG bind address |
| PORT | 8080 | Railway sets this automatically |

## Custom Domain (Optional)

1. Go to Railway dashboard → Settings → Domains
2. Click "Custom Domain"
3. Enter your domain name
4. Add the provided CNAME record to your DNS settings

## Pricing & Free Tier

Railway offers:
- **Free Trial**: $5 credit to start
- **Hobby Plan**: $5/month + usage-based pricing
- **Pricing**: ~$0.000463 per GB-hour of RAM and $0.000231 per vCPU-hour

Your app (512MB RAM, 1 vCPU) will cost approximately:
- ~$3-5/month if running 24/7
- Less if you enable sleep mode

### Cost Optimization:
1. Enable "Sleep Mode" when idle (in Railway settings)
2. Set appropriate health check intervals
3. Monitor usage in the dashboard

## Advantages of Railway over Fly.io

1. **Simpler Setup**: No CLI required for GitHub deployments
2. **Better Dashboard**: More intuitive UI for logs and metrics
3. **Auto-deploys**: Automatic deployments from GitHub
4. **Easy Scaling**: Simple slider for resources
5. **Better Monitoring**: Built-in metrics and alerts
6. **Postgres/Redis**: Easy to add if needed later

## Troubleshooting

### 1. Check Deployment Logs
In Railway dashboard → Deployments → Click on deployment → View logs

### 2. Check Build Logs
In Railway dashboard → Deployments → Click on "Build" phase

### 3. Common Issues

**Issue**: Build fails
- Check Docker build logs in Railway dashboard
- Verify Dockerfile syntax
- Check if all required files are in repository

**Issue**: App crashes after deploy
- Check runtime logs
- Verify environment variables are set
- Check if health check endpoint responds
- Ensure start.sh has execute permissions (chmod +x)

**Issue**: Out of memory
- In Railway dashboard → Settings → Resources
- Increase memory allocation
- Monitor metrics to find optimal size

**Issue**: Slow startup
- Normal for SearXNG (takes 30-60s)
- Health check timeout is set to 100s
- First request may be slower

### 4. View Live Logs
```bash
railway logs --follow
```

### 5. SSH into Container (if needed)
```bash
railway shell
```

## Migration from Fly.io

If you're migrating from Fly.io:

1. **Keep Fly.io running** while testing Railway
2. **Test Railway deployment** thoroughly
3. **Update DNS/endpoints** to point to Railway
4. **Destroy Fly.io app** once confirmed working:
   ```bash
   flyctl apps destroy your-app-name
   ```

## Rollback

If you need to rollback:
1. Go to Railway dashboard → Deployments
2. Find the previous working deployment
3. Click "Redeploy" on that deployment

## Support

- Railway Docs: https://docs.railway.app/
- Railway Discord: https://discord.gg/railway
- Status Page: https://railway.app/status

## Next Steps

After deployment:
1. ✅ Verify all endpoints work
2. ✅ Set up custom domain (optional)
3. ✅ Configure GitHub auto-deploys
4. ✅ Monitor logs and metrics
5. ✅ Set up alerts (optional)
6. ✅ Integrate with your LLM application
