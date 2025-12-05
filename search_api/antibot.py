"""
Anti-Bot Detection Module

Detects various bot protection services and provides information about:
- Cloudflare (Challenge, Turnstile, Under Attack Mode)
- reCAPTCHA (v2, v3)
- hCaptcha
- DataDome
- Akamai Bot Manager
- PerimeterX
- Imperva/Incapsula
- Kasada

Usage:
    from antibot import detect_protection, is_blocked
    
    response = await client.get(url)
    protection = detect_protection(response.text, response.headers)
    if is_blocked(response):
        # Handle blocked request
"""

import re
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class ProtectionType(Enum):
    """Types of bot protection detected"""
    CLOUDFLARE = "cloudflare"
    CLOUDFLARE_CHALLENGE = "cloudflare_challenge"
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"
    CLOUDFLARE_UNDER_ATTACK = "cloudflare_under_attack"
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    DATADOME = "datadome"
    AKAMAI = "akamai"
    PERIMETERX = "perimeterx"
    IMPERVA = "imperva"
    KASADA = "kasada"
    GENERIC_CAPTCHA = "generic_captcha"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    BOT_DETECTED = "bot_detected"


@dataclass
class ProtectionResult:
    """Result of bot protection detection"""
    is_protected: bool
    is_blocked: bool
    protections: List[ProtectionType] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 to 1.0
    details: Dict[str, str] = field(default_factory=dict)
    recommendation: str = ""
    
    def __str__(self) -> str:
        if not self.is_protected:
            return "No protection detected"
        
        protection_names = [p.value for p in self.protections]
        return f"Protections: {', '.join(protection_names)} (confidence: {self.confidence:.0%})"


# Detection patterns
CLOUDFLARE_PATTERNS = {
    "headers": [
        ("cf-ray", None),
        ("cf-cache-status", None),
        ("server", "cloudflare"),
    ],
    "body": [
        r"cloudflare",
        r"cf-browser-verification",
        r"__cf_chl_rt_tk",
        r"cdn-cgi/challenge-platform",
        r"<title>Just a moment\.\.\.</title>",
        r"checking your browser",
        r"ray id:",
    ],
    "challenge_body": [
        r"cf_chl_managed_tk",
        r"cf_chl_prog",
        r"challenge-platform/h/g/scripts/jsd",
        r"turnstile\.js",
    ],
}

RECAPTCHA_PATTERNS = {
    "body": [
        r"google\.com/recaptcha",
        r"grecaptcha\.",
        r"g-recaptcha",
        r"recaptcha-token",
        r"recaptcha\.net",
    ],
    "v2_specific": [
        r'data-sitekey="',
        r"g-recaptcha-response",
    ],
    "v3_specific": [
        r"grecaptcha\.execute",
        r"recaptcha/api\.js\?render=",
    ],
}

HCAPTCHA_PATTERNS = {
    "body": [
        r"hcaptcha\.com",
        r"h-captcha",
        r"hcaptcha-sitekey",
        r"hcaptcha\.render",
    ],
}

DATADOME_PATTERNS = {
    "headers": [
        ("x-datadome", None),
        ("server", "datadome"),
    ],
    "body": [
        r"datadome\.co",
        r"dd\.js",
        r"datadome-cid",
    ],
}

AKAMAI_PATTERNS = {
    "headers": [
        ("x-akamai-transformed", None),
        ("akamai-grn", None),
    ],
    "body": [
        r"akamaized\.net",
        r"_abck",
        r"ak_bmsc",
        r"bm_sz",
        r"sensor_data",
    ],
}

PERIMETERX_PATTERNS = {
    "headers": [
        ("x-px-", None),
    ],
    "body": [
        r"perimeterx",
        r"_pxhd",
        r"px-captcha",
        r"human-challenge",
    ],
}

IMPERVA_PATTERNS = {
    "headers": [
        ("x-iinfo", None),
        ("x-cdn", "Imperva"),
    ],
    "body": [
        r"incapsula",
        r"imperva",
        r"_IIVS-",
        r"reese84",
    ],
}

KASADA_PATTERNS = {
    "body": [
        r"kasada",
        r"cd\.js",
        r"_kpsdk",
    ],
}

BLOCKED_STATUS_CODES = {403, 429, 503, 520, 521, 522, 523, 524}

BLOCKED_TITLE_PATTERNS = [
    r"access denied",
    r"blocked",
    r"forbidden",
    r"not allowed",
    r"bot detected",
    r"automated access",
    r"please verify",
    r"captcha",
    r"just a moment",
    r"checking your browser",
    r"suspicious activity",
    r"rate limit",
    r"too many requests",
]


def _check_header_patterns(
    headers: Dict[str, str],
    patterns: List[tuple]
) -> bool:
    """Check if headers match any patterns"""
    headers_lower = {k.lower(): v.lower() for k, v in headers.items()}
    
    for header_name, expected_value in patterns:
        header_name = header_name.lower()
        if header_name in headers_lower:
            if expected_value is None:
                return True
            if expected_value.lower() in headers_lower[header_name]:
                return True
    return False


def _check_body_patterns(html: str, patterns: List[str]) -> List[str]:
    """Check if body matches patterns, return matched patterns"""
    html_lower = html.lower()
    matched = []
    for pattern in patterns:
        if re.search(pattern, html_lower, re.IGNORECASE):
            matched.append(pattern)
    return matched


def _extract_title(html: str) -> Optional[str]:
    """Extract page title from HTML"""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def detect_protection(
    html: str,
    headers: Optional[Dict[str, str]] = None
) -> ProtectionResult:
    """
    Detect bot protection mechanisms in a response
    
    Args:
        html: HTML content of the response
        headers: Response headers (optional but recommended)
        
    Returns:
        ProtectionResult with detection details
    """
    headers = headers or {}
    protections: List[ProtectionType] = []
    details: Dict[str, str] = {}
    confidence = 0.0
    
    # Check Cloudflare
    cf_header_match = _check_header_patterns(headers, CLOUDFLARE_PATTERNS["headers"])
    cf_body_matches = _check_body_patterns(html, CLOUDFLARE_PATTERNS["body"])
    cf_challenge_matches = _check_body_patterns(html, CLOUDFLARE_PATTERNS["challenge_body"])
    
    if cf_header_match or cf_body_matches:
        if cf_challenge_matches:
            if "turnstile" in "".join(cf_challenge_matches).lower():
                protections.append(ProtectionType.CLOUDFLARE_TURNSTILE)
                details["cloudflare"] = "Turnstile challenge detected"
            elif "challenge-platform" in html.lower():
                protections.append(ProtectionType.CLOUDFLARE_CHALLENGE)
                details["cloudflare"] = "JavaScript challenge detected"
            elif "just a moment" in html.lower():
                protections.append(ProtectionType.CLOUDFLARE_UNDER_ATTACK)
                details["cloudflare"] = "Under attack mode detected"
            else:
                protections.append(ProtectionType.CLOUDFLARE_CHALLENGE)
                details["cloudflare"] = "Challenge page detected"
            confidence = max(confidence, 0.9)
        else:
            protections.append(ProtectionType.CLOUDFLARE)
            details["cloudflare"] = "Cloudflare CDN detected (not blocking)"
            confidence = max(confidence, 0.7)
    
    # Check reCAPTCHA
    recaptcha_matches = _check_body_patterns(html, RECAPTCHA_PATTERNS["body"])
    if recaptcha_matches:
        v3_matches = _check_body_patterns(html, RECAPTCHA_PATTERNS["v3_specific"])
        if v3_matches:
            protections.append(ProtectionType.RECAPTCHA_V3)
            details["recaptcha"] = "reCAPTCHA v3 (invisible) detected"
        else:
            protections.append(ProtectionType.RECAPTCHA_V2)
            details["recaptcha"] = "reCAPTCHA v2 detected"
        confidence = max(confidence, 0.85)
    
    # Check hCaptcha
    hcaptcha_matches = _check_body_patterns(html, HCAPTCHA_PATTERNS["body"])
    if hcaptcha_matches:
        protections.append(ProtectionType.HCAPTCHA)
        details["hcaptcha"] = "hCaptcha detected"
        confidence = max(confidence, 0.85)
    
    # Check DataDome
    dd_header_match = _check_header_patterns(headers, DATADOME_PATTERNS["headers"])
    dd_body_matches = _check_body_patterns(html, DATADOME_PATTERNS["body"])
    if dd_header_match or dd_body_matches:
        protections.append(ProtectionType.DATADOME)
        details["datadome"] = "DataDome protection detected"
        confidence = max(confidence, 0.85)
    
    # Check Akamai
    ak_header_match = _check_header_patterns(headers, AKAMAI_PATTERNS["headers"])
    ak_body_matches = _check_body_patterns(html, AKAMAI_PATTERNS["body"])
    if ak_header_match or ak_body_matches:
        protections.append(ProtectionType.AKAMAI)
        details["akamai"] = "Akamai Bot Manager detected"
        confidence = max(confidence, 0.8)
    
    # Check PerimeterX
    px_header_match = _check_header_patterns(headers, PERIMETERX_PATTERNS["headers"])
    px_body_matches = _check_body_patterns(html, PERIMETERX_PATTERNS["body"])
    if px_header_match or px_body_matches:
        protections.append(ProtectionType.PERIMETERX)
        details["perimeterx"] = "PerimeterX protection detected"
        confidence = max(confidence, 0.85)
    
    # Check Imperva
    imp_header_match = _check_header_patterns(headers, IMPERVA_PATTERNS["headers"])
    imp_body_matches = _check_body_patterns(html, IMPERVA_PATTERNS["body"])
    if imp_header_match or imp_body_matches:
        protections.append(ProtectionType.IMPERVA)
        details["imperva"] = "Imperva/Incapsula protection detected"
        confidence = max(confidence, 0.8)
    
    # Check Kasada
    ks_body_matches = _check_body_patterns(html, KASADA_PATTERNS["body"])
    if ks_body_matches:
        protections.append(ProtectionType.KASADA)
        details["kasada"] = "Kasada protection detected"
        confidence = max(confidence, 0.8)
    
    # Check for generic CAPTCHA
    if not any(p in [ProtectionType.RECAPTCHA_V2, ProtectionType.RECAPTCHA_V3, ProtectionType.HCAPTCHA] for p in protections):
        if re.search(r'captcha', html, re.IGNORECASE):
            protections.append(ProtectionType.GENERIC_CAPTCHA)
            details["captcha"] = "Generic CAPTCHA detected"
            confidence = max(confidence, 0.7)
    
    # Check page title for block indicators
    title = _extract_title(html)
    if title:
        for pattern in BLOCKED_TITLE_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE):
                if ProtectionType.ACCESS_DENIED not in protections:
                    protections.append(ProtectionType.ACCESS_DENIED)
                    details["title_block"] = f"Blocked page title: {title}"
                    confidence = max(confidence, 0.8)
                break
    
    # Determine if blocked
    is_blocked = any(p in [
        ProtectionType.CLOUDFLARE_CHALLENGE,
        ProtectionType.CLOUDFLARE_TURNSTILE,
        ProtectionType.CLOUDFLARE_UNDER_ATTACK,
        ProtectionType.RECAPTCHA_V2,
        ProtectionType.HCAPTCHA,
        ProtectionType.ACCESS_DENIED,
        ProtectionType.BOT_DETECTED,
        ProtectionType.RATE_LIMITED,
    ] for p in protections)
    
    # Generate recommendation
    recommendation = _get_recommendation(protections, is_blocked)
    
    return ProtectionResult(
        is_protected=len(protections) > 0,
        is_blocked=is_blocked,
        protections=protections,
        confidence=confidence,
        details=details,
        recommendation=recommendation
    )


def is_blocked(
    html: str,
    headers: Optional[Dict[str, str]] = None,
    status_code: Optional[int] = None
) -> bool:
    """
    Quick check if a response indicates blocking
    
    Args:
        html: HTML content
        headers: Response headers
        status_code: HTTP status code
        
    Returns:
        True if the response appears to be blocked
    """
    # Check status code
    if status_code and status_code in BLOCKED_STATUS_CODES:
        return True
    
    # Quick title check
    title = _extract_title(html)
    if title:
        for pattern in BLOCKED_TITLE_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE):
                return True
    
    # Full detection
    result = detect_protection(html, headers)
    return result.is_blocked


def _get_recommendation(protections: List[ProtectionType], is_blocked: bool) -> str:
    """Generate recommendation based on detected protections"""
    if not protections:
        return "No special handling required"
    
    if not is_blocked:
        return "Page accessible, consider stealth mode for future requests"
    
    recommendations = []
    
    if any(p.value.startswith("cloudflare") for p in protections):
        recommendations.append("Use JS rendering (ScrapingBee/Browserless) or wait for challenge completion")
    
    if ProtectionType.RECAPTCHA_V2 in protections or ProtectionType.HCAPTCHA in protections:
        recommendations.append("Requires CAPTCHA solving service (2captcha, anti-captcha)")
    
    if ProtectionType.RECAPTCHA_V3 in protections:
        recommendations.append("Use JS rendering with realistic mouse movements")
    
    if ProtectionType.DATADOME in protections:
        recommendations.append("Use residential proxies + JS rendering")
    
    if ProtectionType.AKAMAI in protections:
        recommendations.append("Use curl_cffi with TLS fingerprinting + sensor data handling")
    
    if ProtectionType.PERIMETERX in protections:
        recommendations.append("Use JS rendering with human-like behavior simulation")
    
    if ProtectionType.RATE_LIMITED in protections:
        recommendations.append("Implement request delays and backoff strategy")
    
    if not recommendations:
        recommendations.append("Try high stealth mode with JS rendering")
    
    return "; ".join(recommendations)


def get_bypass_strategies(protection_type: ProtectionType) -> List[str]:
    """
    Get list of bypass strategies for a specific protection type
    
    Args:
        protection_type: The type of protection to bypass
        
    Returns:
        List of strategy names in order of effectiveness
    """
    strategies = {
        ProtectionType.CLOUDFLARE: ["stealth_medium", "js_render"],
        ProtectionType.CLOUDFLARE_CHALLENGE: ["js_render", "scrapingbee", "browserless"],
        ProtectionType.CLOUDFLARE_TURNSTILE: ["scrapingbee", "browserless", "flaresolverr"],
        ProtectionType.CLOUDFLARE_UNDER_ATTACK: ["wait_and_retry", "js_render"],
        ProtectionType.RECAPTCHA_V2: ["captcha_service", "scrapingbee_premium"],
        ProtectionType.RECAPTCHA_V3: ["js_render", "stealth_high"],
        ProtectionType.HCAPTCHA: ["captcha_service", "scrapingbee_premium"],
        ProtectionType.DATADOME: ["residential_proxy", "stealth_high", "js_render"],
        ProtectionType.AKAMAI: ["curl_cffi", "stealth_high"],
        ProtectionType.PERIMETERX: ["js_render", "stealth_high"],
        ProtectionType.IMPERVA: ["js_render", "stealth_high"],
        ProtectionType.KASADA: ["js_render", "stealth_high"],
        ProtectionType.RATE_LIMITED: ["delay", "proxy_rotation"],
        ProtectionType.ACCESS_DENIED: ["proxy_rotation", "stealth_high"],
    }
    
    return strategies.get(protection_type, ["stealth_high", "js_render"])
