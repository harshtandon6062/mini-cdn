"""The origin's "website content": a product catalogue and simple HTML pages.

In a real company this would come from a database or a CMS. Here it is
hard-coded so the project has no database and the content (and therefore
the ETags) stays the same between requests.
"""

import hashlib
from pathlib import Path

from pydantic import BaseModel


class Product(BaseModel):
    id: int
    name: str
    category: str
    price: float


PRODUCTS: list[Product] = [
    Product(id=1, name="Mechanical Keyboard", category="hardware", price=89.0),
    Product(id=2, name="USB-C Hub", category="hardware", price=35.5),
    Product(id=3, name="HTTP: The Definitive Guide", category="books", price=42.0),
    Product(id=4, name="High Performance Browser Networking", category="books", price=38.0),
]

# Cache busting: the CSS file is served under a name that contains a hash of
# its contents (e.g. styles.3fa1c2d4.css). If the CSS changes, the name
# changes, so every cache treats it as a brand-new URL. That lets us cache
# the file "forever" without ever serving a stale version.
CSS_BYTES = (Path(__file__).parent / "static" / "styles.css").read_bytes()
CSS_HASH = hashlib.sha256(CSS_BYTES).hexdigest()[:8]
CSS_URL = f"/static/styles.{CSS_HASH}.css"


def render_page(title: str, body_html: str) -> bytes:
    """Wrap page content in a shared HTML layout."""
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | Mini Shop</title>
  <link rel="stylesheet" href="{CSS_URL}">
</head>
<body>
  <nav><a href="/">Home</a> <a href="/products">Products</a> <a href="/about">About</a></nav>
  <main><h1>{title}</h1>{body_html}</main>
</body>
</html>"""
    return html.encode()


def home_page() -> bytes:
    return render_page(
        "Welcome",
        "<p>This page is served by the <strong>origin</strong>. "
        "Look at the <code>X-Cache</code> header to see if the edge answered instead.</p>",
    )


def about_page() -> bytes:
    return render_page("About", "<p>A tiny demo shop used to show how a CDN edge caches content.</p>")


def products_page() -> bytes:
    items = "".join(f"<li>{p.name} <span>${p.price:.2f}</span></li>" for p in PRODUCTS)
    return render_page("Products", f"<ul class='products'>{items}</ul>")
