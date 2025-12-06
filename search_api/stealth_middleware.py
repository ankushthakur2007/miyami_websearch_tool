"""
Scrapy downloader middleware that integrates with the existing StealthClient.
Allows Scrapy to use stealth mode for anti-bot bypass.
"""

from scrapy import signals
from scrapy.http import HtmlResponse
from stealth_client import StealthClient, StealthLevel
import asyncio
from typing import Optional


class StealthDownloaderMiddleware:
    """
    Scrapy middleware that uses StealthClient for requests.
    
    Usage in Scrapy settings:
        DOWNLOADER_MIDDLEWARES = {
            'stealth_middleware.StealthDownloaderMiddleware': 585,
        }
        STEALTH_MODE = 'medium'  # off, low, medium, high
    """
    
    def __init__(self, stealth_mode: str = "off"):
        self.stealth_mode = stealth_mode
        self.client: Optional[StealthClient] = None
    
    @classmethod
    def from_crawler(cls, crawler):
        # Get stealth_mode from settings or spider
        stealth_mode = crawler.settings.get('STEALTH_MODE', 'off')
        
        # Instantiate the middleware
        middleware = cls(stealth_mode=stealth_mode)
        
        # Connect the spider_opened signal
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        
        return middleware
    
    def spider_opened(self, spider):
        """Initialize StealthClient when spider opens"""
        spider.logger.info(f'StealthMiddleware: stealth_mode={self.stealth_mode}')
        
        if self.stealth_mode != "off":
            self.client = StealthClient(timeout=30.0)
    
    def spider_closed(self, spider):
        """Cleanup when spider closes"""
        self.client = None
    
    def process_request(self, request, spider):
        """
        Process request using StealthClient if stealth mode is enabled.
        
        Returns HtmlResponse if stealth fetch succeeds, None otherwise.
        """
        if self.stealth_mode == "off" or not self.client:
            # Let Scrapy handle the request normally
            return None
        
        # Use stealth client
        try:
            # Get stealth level
            level = StealthLevel(self.stealth_mode.lower())
            
            # Run async get in sync context (Scrapy uses Twisted)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                response = loop.run_until_complete(
                    self.client.get(request.url, stealth_level=level)
                )
            finally:
                loop.close()
            
            # Return HtmlResponse to Scrapy
            return HtmlResponse(
                url=str(response.url),
                status=response.status_code,
                headers=response.headers,
                body=response.content,
                encoding='utf-8',
                request=request
            )
            
        except Exception as e:
            spider.logger.error(f'StealthClient failed for {request.url}: {e}')
            # Return None to let Scrapy try with its own downloader
            return None
    
    def process_exception(self, request, exception, spider):
        """Handle exceptions"""
        spider.logger.debug(f'StealthMiddleware exception: {exception}')
        return None


class AutoBypassMiddleware:
    """
    Middleware that detects bot protection and automatically escalates stealth levels.
    Works in conjunction with StealthDownloaderMiddleware.
    """
    
    def __init__(self):
        self.failed_urls = set()
    
    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware
    
    def spider_opened(self, spider):
        spider.logger.info('AutoBypassMiddleware enabled')
    
    def process_response(self, request, response, spider):
        """Check response for bot protection"""
        from antibot import detect_protection
        
        # Check for bot protection
        protection = detect_protection(response.text)
        
        if protection.is_blocked:
            spider.logger.warning(
                f'Bot protection detected on {request.url}: '
                f'{[p.value for p in protection.protections]}'
            )
            
            # Mark as failed
            self.failed_urls.add(request.url)
            
            # You could implement retry logic here with higher stealth level
            # For now, just log it
            spider.logger.info(f'Recommendation: {protection.recommendation}')
        
        return response
