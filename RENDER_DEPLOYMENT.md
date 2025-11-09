# Deploy to Render - Step by Step Guide

## Why Render?

✅ **Generous free tier** - 750 hours/month (enough for 24/7)
✅ **Zero config** - Automatic HTTPS, auto-deploys from GitHub
✅ **Simple UI** - Easy to use dashboard
✅ **No credit card** required for free tier
✅ **Better uptime** than Railway/Fly.io free tiers
✅ **Fast deployments** - Usually under 5 minutes

## Prerequisites

1. **GitHub Account** - Your code should be on GitHub
2. **Render Account** - Sign up at [render.com](https://render.com) (free, no credit card needed)

## Deployment Steps

### Method 1: One-Click Deploy (Fastest)

#### Step 1: Push to GitHub (if not done)

```bash
cd /Users/ankushthakur/miyami_search_api
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

#### Step 2: Deploy from Render Dashboard

1. Go to [render.com](https://render.com) and sign in
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Render will auto-detect the Dockerfile and `render.yaml`
5. Click **"Create Web Service"**

That's it! 🎉 Your app will be live in 3-5 minutes.

### Method 2: Using render.yaml (Recommended)

The `render.yaml` file is already configured. Just:

1. Push your code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click **"New +"** → **"Blueprint"**
4. Select your repository
5. Render reads `render.yaml` and auto-configures everything
6. Click **"Apply"**

### Manual Setup (if render.yaml doesn't work)

1. **New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repo

2. **Configure Service**
   ```
   Name: searxng-api
   Region: Oregon (or closest to you)
   Branch: main
   Runtime: Docker
   Instance Type: Free
   ```

3. **Environment Variables**
   ```
   SEARXNG_SECRET = (Render auto-generates, or use: openssl rand -hex 32)
   SEARXNG_DEBUG = 0
   SEARXNG_BIND_ADDRESS = 127.0.0.1:8888
   PORT = 8080
   ```

4. **Health Check**
   ```
   Health Check Path: /health
   ```

5. **Click "Create Web Service"**

## Your App URL

After deployment, your app will be available at:
```
https://searxng-api-xxxx.onrender.com
```

You can find the exact URL in the Render dashboard under your service.

## Testing Your Deployment

### 1. Health Check
```bash
curl https://your-app.onrender.com/health
```

### 2. Search API
```bash
curl "https://your-app.onrender.com/search-api?query=weather"
```

### 3. Fetch API
```bash
curl "https://your-app.onrender.com/fetch?url=https://example.com"
```

### 4. API Documentation
- Swagger UI: `https://your-app.onrender.com/docs`
- ReDoc: `https://your-app.onrender.com/redoc`

## Environment Variables

Set in Render dashboard → Service → Environment:

| Variable | Value | Required |
|----------|-------|----------|
| SEARXNG_SECRET | Auto-generated or `openssl rand -hex 32` | Yes |
| SEARXNG_DEBUG | 0 | Yes |
| SEARXNG_BIND_ADDRESS | 127.0.0.1:8888 | Yes |
| PORT | 8080 | Auto-set by Render |

## Monitoring & Logs

### In Render Dashboard:
1. Go to your service
2. **Logs** tab - Real-time logs with search & filtering
3. **Metrics** tab - CPU, Memory, Request metrics
4. **Events** tab - Deployment history

### Log Viewing:
- Auto-refreshing live logs
- Search and filter capabilities
- Download logs option
- Color-coded by severity

## Auto-Deploys from GitHub

Render automatically deploys when you push to GitHub:

```bash
git add .
git commit -m "Update feature"
git push origin main
```

Render will:
1. Detect the push
2. Build the Docker image
3. Run health checks
4. Deploy automatically (zero downtime)

To disable auto-deploy:
- Go to Service → Settings → Build & Deploy
- Disable "Auto-Deploy"

## Free Tier Details

Render Free Tier includes:
- ✅ **750 hours/month** of runtime (enough for 24/7 with one service)
- ✅ **512 MB RAM**
- ✅ **0.5 CPU**
- ✅ **100 GB bandwidth/month**
- ✅ **Automatic HTTPS** (free SSL)
- ✅ **Custom domains** (free)
- ⚠️ **Spins down after 15 min of inactivity** (free tier limitation)
- ⚠️ **Cold starts** take 30-60 seconds (SearXNG initialization)

### Important Note on Free Tier:
**Your service will spin down after 15 minutes of inactivity**. First request after spin-down will take 30-60 seconds to wake up.

To keep it always active: Upgrade to Starter plan ($7/month).

## Custom Domain (Free)

1. Render Dashboard → Service → Settings
2. Scroll to "Custom Domains"
3. Click "Add Custom Domain"
4. Enter your domain: `api.yourdomain.com`
5. Add the CNAME record to your DNS:
   ```
   CNAME: api.yourdomain.com → your-app.onrender.com
   ```
6. Render auto-provisions free SSL (Let's Encrypt)

## Upgrading from Free Tier

If you need better performance:

**Starter Plan** ($7/month):
- No spin-down (always on)
- Faster builds
- Priority support

**Standard Plan** ($25/month):
- 2 GB RAM
- 1 CPU
- Better for production

Upgrade in: Service → Settings → Plan

## Troubleshooting

### Issue: Deployment Fails

**Check Build Logs:**
1. Render Dashboard → Deployments
2. Click on the failed deployment
3. View build logs

**Common fixes:**
- Verify Dockerfile syntax
- Ensure all files are in GitHub repo
- Check if start.sh has executable permissions

### Issue: App Crashes After Deploy

**Check Runtime Logs:**
1. Render Dashboard → Logs tab
2. Look for error messages

**Common fixes:**
- Verify environment variables are set
- Check if SearXNG starts properly
- Ensure health check endpoint works
- Review memory usage (512MB limit on free tier)

### Issue: Health Check Failing

**Adjust Health Check Settings:**
1. Service → Settings → Health & Alerts
2. Health Check Path: `/health`
3. Health Check Grace Period: 180 seconds (give SearXNG time to start)

### Issue: Out of Memory (OOM)

**Solutions:**
- Upgrade to Starter plan (more RAM)
- Or optimize Docker image (remove unnecessary dependencies)

### Issue: Slow Cold Starts

**This is normal on free tier:**
- Free tier spins down after 15 min inactivity
- SearXNG takes 30-60s to initialize
- First request will be slow

**Solutions:**
- Upgrade to Starter ($7/month) for no spin-down
- Or use a uptime monitor to ping every 14 min (e.g., UptimeRobot)

## Keeping Free Tier Always Active (Hack)

Use a free uptime monitor to ping your service every 14 minutes:

**UptimeRobot (Free):**
1. Sign up at [uptimerobot.com](https://uptimerobot.com)
2. Add monitor:
   - Type: HTTP(s)
   - URL: `https://your-app.onrender.com/health`
   - Monitoring Interval: 5 minutes
3. This keeps your service from spinning down

**Note:** Render allows this, but be mindful of bandwidth limits.

## Comparing: Render vs Railway vs Fly.io

| Feature | Render Free | Railway Free | Fly.io Free |
|---------|-------------|--------------|-------------|
| RAM | 512 MB | 512 MB | 256 MB |
| CPU | 0.5 | 0.5 vCPU | Shared |
| Bandwidth | 100 GB | 100 GB | 160 GB |
| Always On | No (spins down) | $5 credit/mo | No (spins down) |
| Custom Domain | ✅ Free | ✅ Free | ✅ Free |
| Auto HTTPS | ✅ | ✅ | ✅ |
| Auto Deploy | ✅ | ✅ | Manual |
| Dashboard | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Ease of Use | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

**Recommendation:** Render is best for your use case!

## Render CLI (Optional)

Install Render CLI for local management:

```bash
# Install
brew tap render-oss/render
brew install render

# Login
render login

# View services
render services list

# View logs
render logs -s your-service-name

# Deploy manually
render deploy -s your-service-name
```

## Rollback Deployments

If a deployment breaks something:

1. Render Dashboard → Deployments
2. Find the last working deployment
3. Click "Redeploy" button

Instant rollback! 🎉

## Notifications & Alerts

Set up alerts for:
- Deploy failures
- Service crashes
- High memory usage

Go to: Service → Settings → Alerts

## Support & Resources

- 📚 [Render Docs](https://render.com/docs)
- 💬 [Community Forum](https://community.render.com/)
- 📧 [Email Support](https://render.com/support)
- 📊 [Status Page](https://status.render.com/)

## Migration Checklist

If migrating from Fly.io/Railway:

- [x] Push code to GitHub
- [x] Create Render account
- [x] Deploy to Render
- [x] Test all endpoints
- [x] Update DNS (if using custom domain)
- [x] Monitor for 24-48 hours
- [ ] Delete old deployment

## Security Best Practices

1. **Environment Variables**: Never commit secrets to Git
2. **HTTPS Only**: Render provides free SSL automatically
3. **Health Checks**: Monitor your service uptime
4. **Logs**: Review logs regularly for errors
5. **Updates**: Keep dependencies updated

## Cost Estimation

**Free Tier:** $0/month
- Perfect for development & testing
- Handles moderate traffic
- Spins down after inactivity

**Starter Plan:** $7/month
- Always on (no spin-down)
- Better for production
- Recommended for production use

**Your app estimated cost on Starter:** $7/month (fixed)

## Next Steps After Deployment

1. ✅ Test all API endpoints
2. ✅ Set up custom domain (optional)
3. ✅ Configure uptime monitoring
4. ✅ Enable deploy notifications
5. ✅ Monitor logs for first 24 hours
6. ✅ Integrate with your LLM application
7. ✅ Consider upgrading if you need always-on

---

**Ready to deploy?** Just push to GitHub and connect to Render. You'll be live in 5 minutes! 🚀
