import httpx


async def validate_url(url: str) -> dict:
    if not isinstance(url, str) or not url.strip():
        return {"valid": False, "reason": "empty URL"}
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return {"valid": False, "reason": "must start with http:// or https://"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=6) as client:
            r = await client.head(url)
            if r.status_code < 400:
                return {"valid": True, "reason": "reachable"}
            # Some servers reject HEAD — try GET with range
            r2 = await client.get(url, headers={"Range": "bytes=0-0"})
            if r2.status_code < 400:
                return {"valid": True, "reason": "reachable"}
            return {"valid": False, "reason": f"server returned {r.status_code}"}
    except httpx.TimeoutException:
        return {"valid": False, "reason": "timed out — URL may not exist"}
    except Exception as e:
        return {"valid": False, "reason": f"unreachable ({str(e)[:60]})"}
