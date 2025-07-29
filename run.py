import ssl
ssl._DEFAULT_CIPHERS += 'HIGH:!DH:!aNULL'

import urllib3
import os
import json
import hashlib
import base64
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from datetime import datetime
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime

CATEGORY_URL = "https://moh.gov.vn/thong-tin-chi-dao-dieu-hanh" # URL của danh mục cần crawl
API_URL = "http://45.122.253.178:8081/portal/api/SaveTinbai" # URL API để gửi bài viết
UPLOAD_FILE_URL = "http://45.122.253.178:8081/portal/servletws/uploadfile/UploadTinTucFormData"  # URL để upload file đính kèm
UPLOAD_URL = "http://45.122.253.178:8081/portal/plugins/ckfinder/core/connector/java/connector.java?command=QuickUpload&type=Images&CKEditor=content&CKEditorFuncNum=1&langCode=vi" # URL để upload ảnh
COOKIE_HEADER = "JSESSIONID=1C1ECC0A0E94B5587FC36AB37DB9D563;CKFinder_Path=Images%3A%2F%3A1;ckCsrfToken=OGcSM0zD5dAt7bbgdxgeWG29lMsfy33y1dOF0fB7" # Cookie để upload ảnh
COOKIE_HEADER_FILE = "JSESSIONID=97E643E0D1ACE234EBCF27FB355C2833;CKFinder_Path=Images%3A%2F%3A1;ckCsrfToken=OGcSM0zD5dAt7bbgdxgeWG29lMsfy33y1dOF0fB7" # Cookie để upload file đính kèm
CSRF_TOKEN = "OGcSM0zD5dAt7bbgdxgeWG29lMsfy33y1dOF0fB7" # CSRF token để upload ảnh
MAX_ARTICLES = 5 # Số lượng bài viết tối đa mỗi trang
MAX_PAGES = 1 # Số lượng trang tối đa để duyệt
FILTER_FROM_DATE = "20-07-2025"  #Trở về sau VD: "01-01-2020"
FILTER_TO_DATE = "22-07-2025"    #Trở về trước VD: "31-12-2020"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs("images", exist_ok=True)
os.makedirs("documents", exist_ok=True)

class CustomAdapter(HTTPAdapter): # Tùy chỉnh adapter để sử dụng SSL với ciphers an toàn
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            **pool_kwargs
        )

session = requests.Session()
session.mount("https://", CustomAdapter())

def is_in_date_range(date_str): # Kiểm tra ngày
    """Kiểm tra bài viết có nằm trong khoảng thời gian không"""
    try:
        if not date_str:
            return False
        article_date = datetime.strptime(date_str, "%d-%m-%Y %I:%M %p")
        if FILTER_FROM_DATE:
            from_date = datetime.strptime(FILTER_FROM_DATE, "%d-%m-%Y")
            if article_date < from_date:
                return False
        if FILTER_TO_DATE:
            to_date = datetime.strptime(FILTER_TO_DATE, "%d-%m-%Y")
            if article_date > to_date:
                return False
        return True
    except Exception as e:
        print("Lỗi so sánh ngày:", e)
        return False

def download_image(img_url): # Tải ảnh từ URL
    try:
        if img_url.startswith("data:image"):
            return ""
        if not img_url.startswith("http"):
            img_url = urljoin("https://moh.gov.vn", img_url)

        response = session.get(img_url, timeout=10)
        if response.status_code == 200:
            ext = img_url.split('.')[-1].split('?')[0]
            ext = ext if len(ext) <= 5 else "jpg"
            name_hash = hashlib.md5(img_url.encode()).hexdigest()
            filename = f"{name_hash}.{ext}"
            filepath = os.path.join("images", filename)
            with open(filepath, "wb") as f:
                f.write(response.content)
            return filepath
        else:
            print(f"Không thể tải ảnh: {img_url}")
            return ""
    except Exception as e:
        print(f"Lỗi khi tải ảnh: {img_url} - {e}")
        return ""


def upload_image(filepath): # Upload ảnh đã tải 
    try:
        with open(filepath, 'rb') as f:
            files = {
                'upload': (os.path.basename(filepath), f, 'image/jpeg')
            }
            data = {
                'ckCsrfToken': CSRF_TOKEN
            }
            headers = {
                'Cookie': COOKIE_HEADER
            }
            response = requests.post(UPLOAD_URL, files=files, data=data, headers=headers, verify=False)
            
            if response.status_code == 200:
                try:
                    res = response.json()
                    
                    if "url" in res:
                        return res["url"]
                    
                    else:
                        return f"http://45.122.253.178:8081/resources/CustomsCMS/ckeditor/images/{os.path.basename(filepath)}"
                except:
                    return f"http://45.122.253.178:8081/resources/CustomsCMS/ckeditor/images/{os.path.basename(filepath)}"
            else:
                print(f"Không thể upload ảnh: {filepath} , Status: {response.status_code}")
                print("Response:", response.text)
                return ""
    except Exception as e:
        print(f"Lỗi khi upload ảnh: {filepath} - {e}")
        return ""


def fix_image_src(content: str) -> str: # Sửa src của ảnh trong nội dung HTML
    soup = BeautifulSoup(content, "lxml")
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            local_path = download_image(src)
            if local_path:
                uploaded_url = upload_image(local_path)
                if uploaded_url:
                    img["src"] = uploaded_url
    return str(soup)

def download_and_upload_files(main_tag): # Tải các file đính kèm
    uploaded_files = []
    for link in main_tag.find_all("a", href=True):
        href = link["href"]
        if "/documents/" in href or href.lower().endswith((".pdf", ".doc", ".docx")):
            file_url = urljoin("https://moh.gov.vn", href)
            os.makedirs("documents", exist_ok=True)

            try:
                resp = session.get(file_url, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 100:  
                    
                    content_disp = resp.headers.get("Content-Disposition", "")
                    if "filename=" in content_disp:
                        file_name = content_disp.split("filename=")[-1].strip('" ')
                    else:
                        
                        parts = file_url.split("/")
                        if "." in parts[-2]:  
                            file_name = parts[-2]
                        else:
                            file_name = parts[-1]  

                 
                    if not file_name.lower().endswith((".pdf", ".doc", ".docx")):
                        file_name += ".pdf"

                    local_path = os.path.join("documents", file_name)

                    
                    with open(local_path, "wb") as f:
                        f.write(resp.content)
                    print(f"Đã tải file: {file_name}")

                    
                    uploaded_url = upload_file(local_path)
                    if uploaded_url:
                        uploaded_files.append(uploaded_url)
                else:
                    print(f"Lỗi tải file (status {resp.status_code} hoặc rỗng): {file_url}")
            except Exception as e:
                print(f"Lỗi tải file: {file_url} , {e}")
    return uploaded_files



def upload_file(filepath): # Upload file đã tải lên
    try:
        with open(filepath, 'rb') as f:
            files = {'file': (os.path.basename(filepath), f)}
            headers = {'Cookie': COOKIE_HEADER_FILE}
            response = requests.post(UPLOAD_FILE_URL, files=files, headers=headers, verify=False)
            if response.status_code == 200:
                try:
                    res = response.json()
                    return res.get("url") or f"{os.path.basename(filepath)}"
                except:
                    return f"{os.path.basename(filepath)}"
            else:
                print(f"Không thể upload file: {filepath} , Status: {response.status_code}")
                print("Response:", response.text)
                return ""
    except Exception as e:
        print(f"Lỗi upload file: {filepath} - {e}")
        return ""



def parse_date_string(raw_date): # Chuyển đổi chuỗi ngày tháng sang định dạng 
    try:
        parts = raw_date.strip().split("ngày")
        if len(parts) == 2:
            date_str = parts[1].strip()
            if len(date_str.split(":")) == 2:
                date_str += ":00"
            dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S")
            return dt.strftime("%d-%m-%Y %I:%M %p") 
    except Exception as e:
        print("Lỗi ngày:", e)
    return ""


def crawl_articles(category_url): 
    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("user-agent=Mozilla/5.0")
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 10)
    driver.get(category_url)
    all_articles = []

    page_count = 0
    while page_count < MAX_PAGES:
        page_count += 1
        try:
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "portlet-body")))
            soup = BeautifulSoup(driver.page_source, 'lxml')
            portlet = soup.select_one("div.portlet-body")
            rows = portlet.select("div.itemm div.row")
            for row in rows[:MAX_ARTICLES]:
                try:
                    a_tag = row.select_one("div.col-md-4.col-xs-5 a")
                    detail_url = a_tag["href"] if a_tag else ""
                    title = row.select_one("h3.asset-title").get_text(strip=True)
                    desc = row.select_one("p.hidden-xs").get_text(strip=True)
                    raw_date = row.select_one("span.time").get_text(strip=True)
                    time_posted = parse_date_string(raw_date)
                    if not is_in_date_range(time_posted):
                        print(f"Bỏ qua bài '{title}' vì không nằm trong khoảng thời gian yêu cầu.")
                        continue
                    img_tag = row.select_one("img")
                    img_url = img_tag['src'] if img_tag else ""
                    local_img = download_image(img_url)
                    uploaded_img = upload_image(local_img) if local_img else ""

                    driver.execute_script("window.open(arguments[0]);", detail_url)
                    driver.switch_to.window(driver.window_handles[-1])
                    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "journal-content-article")))
                    detail_soup = BeautifulSoup(driver.page_source, "lxml")
                    main_tag = detail_soup.select_one("div.journal-content-article")
                    content_html = fix_image_src(str(main_tag)) if main_tag else ""
                    uploaded_files = download_and_upload_files(main_tag)
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                    article = {
                        "title": title,
                        "img": uploaded_img,
                        "desc": desc,
                        "date": time_posted,
                        "content": content_html,
                        "link": detail_url,
                        "files": ",".join(uploaded_files)
                    }

                    all_articles.append(article)
                    post_article(article)

                except Exception as e:
                    print("Lỗi xử lý bài viết:", e)
                    continue

            try:
                next_button = driver.find_element(By.LINK_TEXT, "Tiếp theo")
                if "disabled" in next_button.get_attribute("class"):
                    break
                next_button.click()
            except:
                break

        except Exception as e:
            print("Lỗi tải trang:", e)
            break

    driver.quit()
    return all_articles


def post_article(article): # Gửi bài viết lên API
    today = datetime.now().strftime("%d-%m-%Y")
    payload = {
        "language": "TIENG_VIET",
        "page": "BO_YTE",
        "newtitle": article["title"],
        "mota": article["desc"],
        "url": "",
        "action": "1",
        "id": "",
        "version": "1.02",
        "status": "1",
        "dm": "",
        "userID": "662",
        "componentType": "",
        "selectedCategory": "",
        "video_dinh_kem": "",
        "nguoiviet_input": "",
        "nguoiviet": "0",
        "butdanh": "",
        "relateNewsInternet": "",
        "ngaygui": today,
        "kw": article["title"],
        "content": "",
        "noidung": article["content"],
        "category": "7247",
        "relatedArticleIds": "",
        "isHightlight": "0",
        "kind": "0",
        "files": article.get("files", ""),
        "videos": "",
        "approver": "quantri_bo_yte",
        "startdate": article.get("date", ""),
        "enddate": "",
        "approvedate": "",
        "lengthvalue": "2",
        "newsvalue": "1",
        "royalties": "0",
        "imgvalue": "1" if article["img"] else "0",
        "nguoidang": "quantri_bo_yte"
    }
    try:
        if API_URL.strip():
            response = requests.post(API_URL, json=payload)
            print(f"--> Gửi bài: {article['title']} , Trạng thái: {response.status_code}")
            print("API said:", response.text)
        else:
            print(f" Bài viết: {article['title']}")
    except Exception as e:
        print(f"Lỗi gửi bài: {e}")


if __name__ == "__main__":
    articles = crawl_articles(CATEGORY_URL)
    if articles:
        with open("articles.json", "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print("HOÀN TẤT")
    else:
        print("Không có bài viết nào.")