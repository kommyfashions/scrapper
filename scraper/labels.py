import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def get_meesho_page(context):
    for page in context.pages:
        if "supplier.meesho.com" in page.url:
            return page

    page = context.new_page()
    page.goto("https://supplier.meesho.com/")
    time.sleep(5)
    return page


def wait_for_ui(page):
    print("🔍 Waiting for UI...")
    for _ in range(60):
        try:
            if page.locator("text=Orders").count() > 0:
                print("✅ UI loaded")
                return True
        except:
            pass
        time.sleep(1)
    return False


# ---------------- SAFE CHECK ----------------
def has_orders(page):
    try:
        count_text = page.locator("text=Pending").first.inner_text()
        if "(0)" in count_text:
            return False
        return True
    except:
        return False


def wait_for_processing(page):
    print("⏳ Waiting for processing...")
    try:
        page.wait_for_selector("text=Accepting orders", state="hidden", timeout=60000)
    except:
        pass
    print("✅ Processing done")


def select_all_orders(page):
    print("☑️ Selecting all orders...")

    try:
        page.locator("thead input[type='checkbox']").first.click(timeout=5000)
        return True
    except:
        try:
            page.locator("input[type='checkbox']").first.click(timeout=5000)
            return True
        except:
            print("⚠️ No checkbox found (no orders)")
            return False


def click_accept_modal(page):
    print("📋 Waiting for Accept modal...")
    page.wait_for_selector("div[role='dialog']", timeout=10000)

    page.locator("div[role='dialog'] button:has-text('Accept Order')").click()


def accept_orders(page):
    print("\n📦 Accepting Pending Orders...")

    page.locator("text=Pending").first.click()
    time.sleep(5)

    # EDGE CASE
    if not has_orders(page):
        print("⚠️ No pending orders — skipping accept step")
        return

    if not select_all_orders(page):
        print("⚠️ Could not select orders — skipping")
        return

    page.locator("text=Accept Selected Orders").first.click()
    time.sleep(2)

    click_accept_modal(page)

    wait_for_processing(page)

    print("✅ Orders accepted")


def download_labels(page):
    print("\n📦 Downloading Labels...")

    page.locator("text=Ready to Ship").first.click()
    time.sleep(5)

    if not select_all_orders(page):
        print("⚠️ No ready-to-ship orders — skipping label download")
        return

    print("⬇️ Clicking Label button...")

    page.locator("button:has-text('Label')").last.click()

    print("⏳ Waiting for label generation...")
    time.sleep(8)

    print("✅ Label download triggered")


def main():
    print("🚀 Starting Meesho Bot (CDP MODE)\n")

    with sync_playwright() as p:
        # 🔥 Attach to REAL Chrome (same session)
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")

        context = browser.contexts[0]

        # 🔥 Reuse existing supplier tab
        page = get_meesho_page(context)

        print(f"🧠 Using tab: {page.url}")

        if "Access Denied" in page.content():
            print("❌ Blocked. Open manually once.")
            return

        if not wait_for_ui(page):
            print("❌ UI not loaded")
            return

        accept_orders(page)
        download_labels(page)

        print("\n🏁 DONE")

        time.sleep(5)


if __name__ == "__main__":
    main()