"""
Scrapy spider for site-wide crawling with content extraction.
Integrates with existing Trafilatura extraction and stealth features.
"""

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import DNSLookupError, TimeoutError
from urllib.parse import urlparse
import trafilatura
import json
from typing import Optional, List, Dict, Any
import re


class SiteCrawlerSpider(scrapy.Spider):
    """
    Crawl a website and extract content from each page.
    
    Features:
    - Depth-limited crawling
    - URL pattern filtering
    - Trafilatura-based content extraction
    - Markdown/text/html output
    - Respects robots.txt
    """
    
    name = 'site_crawler'
    
    # Custom settings
    custom_settings = {
        'ROBOTSTXT_OBEY': True,
        'CONCURRENT_REQUESTS': 8,
        'DOWNLOAD_DELAY': 1,  # 1 second delay between requests (polite crawling)
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 1,
        'AUTOTHROTTLE_MAX_DELAY': 3,
        'AUTOTHROTTLE_TARGET_CONCURRENCY': 2.0,
        'HTTPERROR_ALLOW_ALL': False,
        'RETRY_TIMES': 2,
        'DOWNLOAD_TIMEOUT': 30,
    }
    
    def __init__(
        self,
        start_url: str,
        max_pages: int = 50,
        max_depth: int = 2,
        allowed_domains: Optional[List[str]] = None,
        url_patterns: Optional[str] = None,  # Changed to string for CLI args
        exclude_patterns: Optional[str] = None,  # Changed to string for CLI args
        format: str = "markdown",
        include_links: bool = True,
        include_images: bool = True,
        stealth_mode: str = "off",
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        
        self.start_urls = [start_url]
        self.max_pages = int(max_pages)
        self.max_depth = int(max_depth)
        self.output_format = format
        self.include_links = bool(include_links) if not isinstance(include_links, bool) else include_links
        self.include_images = bool(include_images) if not isinstance(include_images, bool) else include_images
        self.stealth_mode = stealth_mode
        
        # Parse domain from start_url
        parsed = urlparse(start_url)
        self.allowed_domains = allowed_domains or [parsed.netloc]
        
        # URL filtering patterns - parse from string if needed
        if isinstance(url_patterns, str) and url_patterns:
            self.url_patterns = [p.strip() for p in url_patterns.split(",") if p.strip()]
        else:
            self.url_patterns = url_patterns or []
        
        if isinstance(exclude_patterns, str) and exclude_patterns:
            self.exclude_patterns = [p.strip() for p in exclude_patterns.split(",") if p.strip()]
        else:
            self.exclude_patterns = exclude_patterns or [
                r'/tag/',
                r'/category/',
                r'/author/',
                r'\.(pdf|zip|jpg|jpeg|png|gif|mp4|avi)$',
                r'#',
                r'\?',
            ]
        
        # Track crawled pages
        self.pages_crawled = 0
        self.results = []
        
        # Link extractor
        self.link_extractor = LinkExtractor(
            allow_domains=self.allowed_domains,
            deny=self.exclude_patterns if not self.url_patterns else [],
            unique=True
        )
    
    def parse(self, response):
        """Parse each page and extract content"""
        
        # Check if max pages reached
        if self.pages_crawled >= self.max_pages:
            self.logger.info(f"Reached max pages limit ({self.max_pages})")
            return
        
        self.pages_crawled += 1
        
        # Extract content using Trafilatura
        extracted_data = self._extract_content(response)
        
        if extracted_data:
            yield {
                'url': response.url,
                'status_code': response.status,
                'depth': response.meta.get('depth', 0),
                **extracted_data
            }
        
        # Follow links if depth allows
        current_depth = response.meta.get('depth', 0)
        if current_depth < self.max_depth:
            links = self.link_extractor.extract_links(response)
            
            # Apply custom URL patterns if specified
            if self.url_patterns:
                links = [
                    link for link in links
                    if any(re.search(pattern, link.url) for pattern in self.url_patterns)
                ]
            
            for link in links:
                if self.pages_crawled < self.max_pages:
                    yield response.follow(
                        link.url,
                        callback=self.parse,
                        errback=self.errback_httpbin,
                        meta={'depth': current_depth + 1}
                    )
    
    def _extract_content(self, response) -> Optional[Dict[str, Any]]:
        """Extract content using Trafilatura (same as /fetch endpoint)"""
        try:
            html_content = response.text
            
            # Extract with Trafilatura
            extracted = trafilatura.extract(
                html_content,
                include_comments=False,
                include_tables=True,
                include_images=self.include_images,
                include_links=self.include_links,
                output_format='json',
                url=response.url,
                with_metadata=True
            )
            
            if not extracted:
                return None
            
            data = json.loads(extracted)
            
            # Build metadata
            metadata = {
                "title": data.get("title", ""),
                "author": data.get("author", ""),
                "sitename": data.get("sitename", ""),
                "date": data.get("date", ""),
                "categories": data.get("categories", []),
                "tags": data.get("tags", []),
                "description": data.get("description", ""),
                "language": data.get("language", ""),
            }
            
            # Clean empty values
            metadata = {k: v for k, v in metadata.items() if v}
            
            # Get content in requested format
            if self.output_format == "markdown":
                content = trafilatura.extract(
                    html_content,
                    include_comments=False,
                    include_tables=True,
                    include_images=self.include_images,
                    include_links=self.include_links,
                    output_format='markdown',
                    url=response.url
                ) or data.get("text", "")
            elif self.output_format == "html":
                content = data.get("raw_text", data.get("text", ""))
            else:
                content = data.get("text", "")
            
            return {
                "metadata": metadata,
                "content": content,
                "word_count": len(content.split()),
                "format": self.output_format
            }
            
        except Exception as e:
            self.logger.error(f"Content extraction failed for {response.url}: {e}")
            return None
    
    def errback_httpbin(self, failure):
        """Handle request errors"""
        self.logger.error(f"Request failed: {repr(failure)}")
        
        if failure.check(HttpError):
            response = failure.value.response
            self.logger.error(f'HttpError on {response.url}')
        elif failure.check(DNSLookupError):
            request = failure.request
            self.logger.error(f'DNSLookupError on {request.url}')
        elif failure.check(TimeoutError):
            request = failure.request
            self.logger.error(f'TimeoutError on {request.url}')
