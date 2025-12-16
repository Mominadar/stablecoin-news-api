from bs4 import BeautifulSoup

def parse_description(raw_desc: str):
    """
    Takes the raw description string (may be plain text or HTML).
    Returns:
      - clean_text: stripped text content
      - image_urls: list of image src URLs found in <img> tags
    """
    if raw_desc is None:
        return "", []

    # Parse as HTML regardless; safe for plain text too
    soup = BeautifulSoup(raw_desc, "html.parser")

    # Get text, strip leading/trailing whitespace
    clean_text = soup.get_text(" ", strip=True)

    # Extract all <img> URLs
    image_urls = [
        img.get("src")
        for img in soup.find_all("img")
        if img.get("src")
    ]

    if len(image_urls) == 0:
        image = None
    else:
        image = image_urls[0]
        
    return clean_text, image
