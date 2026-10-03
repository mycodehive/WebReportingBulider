"""Exercise rendered Django admin pages with the real CSS and native theme script."""
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders


@pytest.mark.django_db
def test_admin_themes_and_responsive_layout(client):
    playwright = pytest.importorskip("playwright.sync_api")
    user = get_user_model().objects.create_superuser("admin-layout", "layout@example.test", "test-password")
    client.force_login(user)
    paths = ["/admin/", "/admin/reportbuilder/connection/", "/admin/reportbuilder/asset/add/",
             f"/admin/auth/user/{user.pk}/change/", "/admin/jsi18n/"]
    # Serve actual rendered responses without requiring a TCP listener. Static
    # assets still come from Django's finders, including the shipped admin CSS.
    responses = {}
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        responses[path] = (response.content, response["Content-Type"])
    client.logout()
    response = client.get("/admin/login/")
    responses["/admin/login/"] = (response.content, response["Content-Type"])

    def serve(route):
        path = urlparse(route.request.url).path
        if path.startswith("/static/"):
            asset = finders.find(path.removeprefix("/static/"))
            assert asset, path
            route.fulfill(body=Path(asset).read_bytes(),
                          content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
        else:
            body, content_type = responses[path]
            route.fulfill(body=body, content_type=content_type)

    with playwright.sync_playwright() as api:
        try:
            browser = api.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium binary is unavailable")
            raise
        page = browser.new_page()
        page.route("http://testserver/**", serve)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        shots = Path("test-results")
        shots.mkdir(exist_ok=True)
        try:
            for width in (1440, 1024, 390):
                page.set_viewport_size({"width": width, "height": 1000})
                for theme in ("light", "dark"):
                    page.goto("http://testserver/admin/")
                    page.evaluate("theme => localStorage.setItem('theme', theme)", theme)
                    for path in [*paths[:4], "/admin/login/"]:
                        page.goto("http://testserver" + path)
                        playwright.expect(page.locator("html")).to_have_attribute("data-theme", theme)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), path
                        assert page.locator("#content").bounding_box()["width"] <= width
                        if path != "/admin/login/":
                            header = page.locator("#header").bounding_box()
                            tools = page.locator("#user-tools").bounding_box()
                            assert tools["y"] + tools["height"] <= header["y"] + header["height"]
                        if path.endswith("/change/") or path.endswith("/add/"):
                            for save in page.locator(".submit-row input").all():
                                assert 40 <= save.bounding_box()["height"] <= 60
                        assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == (
                            "rgb(244, 247, 252)" if theme == "light" else "rgb(11, 18, 32)"
                        )
                        if path == "/admin/":
                            main = page.locator("#content-main").bounding_box()
                            recent = page.locator("#content-related").bounding_box()
                            if width == 390:
                                assert recent["y"] >= main["y"] + main["height"]
                            else:
                                assert recent["x"] >= main["x"] + main["width"]
                            page.screenshot(path=str(shots / f"admin-{theme}-{width}.png"), full_page=True)
                        if path.endswith("asset/add/"):
                            playwright.expect(page.locator("#id_name")).to_be_visible()
                            page.locator("#id_name").fill("Layout check")
                            playwright.expect(page.locator("#id_name")).to_have_value("Layout check")
                    page.goto("http://testserver/admin/reportbuilder/connection/")
                    add = page.locator(".object-tools a.addlink")
                    assert add.evaluate("e => getComputedStyle(e).borderRadius") == "0px"
                    assert add.evaluate("e => getComputedStyle(e).backgroundImage") == "none"
                    title, button = page.locator("#content h1").bounding_box(), add.bounding_box()
                    assert button["y"] >= title["y"] + title["height"]
            # Theme choice persists across pages. System mode responds to OS changes.
            page.locator(".theme-toggle").click()
            playwright.expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.reload()
            playwright.expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.locator(".theme-toggle").click()
            page.reload()
            playwright.expect(page.locator("html")).to_have_attribute("data-theme", "auto")
            page.emulate_media(color_scheme="dark")
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(11, 18, 32)"
            page.emulate_media(color_scheme="light")
            assert page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(244, 247, 252)"
            assert errors == []
        finally:
            browser.close()
