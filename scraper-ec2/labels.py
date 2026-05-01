import time
from playwright.sync_api import sync_playwright

DEBUG_PORT = "http://127.0.0.1:9222"

PENDING_URL = "https://supplier.meesho.com/panel/v3/new/fulfillment/hrbib/orders/pending"
READY_URL = "https://supplier.meesho.com/panel/v3/new/fulfillment/hrbib/orders/ready-to-ship"


# =========================
# ALWAYS OPEN CORRECT PAGE
# =========================
def open_orders_page(context):
    page = context.new_page()
    page.goto(PENDING_URL)
    time.sleep(5)

    print(f"🌐 Opened: {page.url}")
    return page


def log_url(page, step):
    print(f"🌍 [{step}] URL → {page.url}")


def wait_for_ui(page):
    print("🔍 Waiting for UI...")
    for _ in range(60):
        if page.locator("text=Orders").count() > 0:
            print("✅ UI loaded")
            return True
        time.sleep(1)
    return False


def refresh(page, label=""):
    print(f"🔄 Refreshing {label}")
    page.reload()
    time.sleep(5)
    log_url(page, f"after refresh {label}")


def wait_for_orders(page):
    print("⏳ Waiting for orders...")
    for _ in range(20):
        rows = page.locator("tbody tr").count()
        if rows > 0:
            print(f"✅ Orders found: {rows}")
            return True
        time.sleep(1)
    print("⚠️ No orders found")
    return False


def click_select_all(page):
    print("☑️ Selecting all orders...")

    for _ in range(10):
        checkboxes = page.locator("input[type='checkbox']")
        if checkboxes.count() > 0:
            try:
                checkboxes.first.click(timeout=3000)
                print("✅ Checkbox clicked")
                return True
            except:
                page.evaluate("""
                    document.querySelectorAll('input[type="checkbox"]')[0]?.click()
                """)
                print("✅ Checkbox clicked (JS)")
                return True
        time.sleep(1)

    print("❌ Checkbox not found")
    return False


# =========================
# ACCEPT FLOW
# =========================
def accept_pending(page):
    print("\n➡️ Pending Flow")

    page.goto(PENDING_URL)
    time.sleep(3)
    log_url(page, "Pending open")

    refresh(page, "Pending")

    if not wait_for_orders(page):
        return False

    if not click_select_all(page):
        return False

    page.locator("text=Accept Selected Orders").click()
    time.sleep(2)

    try:
        page.locator("button:has-text('Accept Order')").click()
        print("✅ Accepted orders")
    except:
        print("⚠️ Accept modal missing")

    print("⏳ Waiting backend processing...")
    time.sleep(10)

    refresh(page, "After Accept")

    return True


# =========================
# DOWNLOAD FLOW
# =========================
def download_labels(page):
    print("\n➡️ Ready-to-Ship Flow")

    page.goto(READY_URL)
    time.sleep(3)
    log_url(page, "Ready open")

    refresh(page, "Ready")

    if not wait_for_orders(page):
        return

    if not click_select_all(page):
        return

    print("⬇️ Downloading labels...")
    page.locator("button:has-text('Label')").last.click()

    time.sleep(8)
    print("✅ Download triggered")


# =========================
# MAIN
# =========================
def main():
    print("🚀 START (FINAL STABLE v2)\n")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(DEBUG_PORT)
        context = browser.contexts[0]

        page = open_orders_page(context)

        if not wait_for_ui(page):
            return

        accepted = accept_pending(page)

        download_labels(page)

        print("\n🏁 DONE")
        time.sleep(5)


if __name__ == "__main__":
    main()