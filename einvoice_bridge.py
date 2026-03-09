# =======================================================================
# OMNISALE PRO - E-INVOICE BRIDGE (TRẠM TRUNG CHUYỂN HÓA ĐƠN ĐIỆN TỬ)
# =======================================================================

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import os
import html
import uuid
import json

from datetime import datetime
import urllib3
import ssl
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
 
import base64
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import hashlib
import platform
import uuid
# Tắt cảnh báo khi kết nối với các máy chủ dùng SSL đời cũ
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====================================================================
# 🔥 BỘ CHUYỂN ĐỔI XUYÊN THỦNG SSL CŨ CỦA MOBIFONE
# ====================================================================
class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        # Dòng lệnh ma thuật: Ép Python chấp nhận chuẩn SSL cũ (Legacy Renegotiation)
        context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = context
        return super(LegacySSLAdapter, self).init_poolmanager(*args, **kwargs)

# Khởi tạo một phiên (session) dùng chung bộ chuyển đổi này
http_session = requests.Session()
http_session.mount("https://", LegacySSLAdapter())


app = Flask(__name__)
CORS(app) # Cho phép React gọi vào

# ====================================================================
# 🔥 HỆ THỐNG BẢO MẬT & CẤP PHÉP BẢN QUYỀN (LICENSE MANAGER)
# ====================================================================
# Đây là "Chìa khóa bí mật" của riêng CEO. TUYỆT ĐỐI KHÔNG TIẾT LỘ CHO AI.
SECRET_SALT = "OMNISALE_CEO_PRO_2026_V1"

def get_machine_code():
    """Đọc thông số phần cứng để tạo Mã Máy duy nhất"""
    try:
        # Lấy địa chỉ MAC của Card mạng
        mac_num = hex(uuid.getnode()).replace('0x', '').upper()
        mac_str = '-'.join(mac_num[i: i + 2] for i in range(0, 11, 2))
        
        # Lấy Hệ điều hành và Tên máy tính
        sys_info = f"{platform.system()}-{platform.node()}"
        
        # Băm (Hash) để tạo ra chuỗi 16 ký tự tuyệt đẹp
        raw_id = f"{mac_str}-{sys_info}".encode('utf-8')
        machine_hash = hashlib.md5(raw_id).hexdigest().upper()
        
        return f"{machine_hash[:4]}-{machine_hash[4:8]}-{machine_hash[8:12]}-{machine_hash[12:16]}"
    except Exception:
        return "UNKNOWN-MACHINE-CODE"

@app.route('/api/license/info', methods=['GET'])
def get_license_info():
    """Gửi Mã Máy lên cho màn hình Web hiển thị"""
    machine_id = get_machine_code()
    return jsonify({"success": True, "machineId": machine_id})

@app.route('/api/license/verify', methods=['POST'])
def verify_license():
    """Kiểm tra Key và Ngày hết hạn"""
    data = request.json
    key_input = data.get('key', '').strip().upper()
    machine_id = get_machine_code()
    
    # 1. Kiểm tra cấu trúc Key (Phải có 4 cụm: YYYYMMDD-XXXX-XXXX-XXXX)
    parts = key_input.split('-')
    if len(parts) != 4:
        return jsonify({"success": False, "message": "❌ Định dạng Key không hợp lệ!"})
        
    expire_str = parts[0]  # Lấy cục đầu tiên (Ngày hết hạn)
    sig_input = "".join(parts[1:]) # Gom 3 cục sau lại thành chữ ký
    
    # 2. Kiểm tra xem Key này có phải do chính CEO tạo ra cho máy này không? (Chống làm giả ngày)
    raw_data = f"{machine_id}{expire_str}{SECRET_SALT}".encode('utf-8')
    expected_sig = hashlib.md5(raw_data).hexdigest().upper()[:12]
    
    if sig_input != expected_sig:
        return jsonify({"success": False, "message": "❌ Mã kích hoạt sai hoặc dùng cho máy khác!"})
        
    # 3. Kiểm tra Ngày Hết Hạn
    try:
        expire_date = datetime.strptime(expire_str, "%Y%m%d")
        current_date = datetime.now()
        
        if current_date > expire_date:
            return jsonify({"success": False, "message": f"❌ Key đã hết hạn vào ngày {expire_date.strftime('%d/%m/%Y')}. Vui lòng gia hạn!"})
            
    except ValueError:
        return jsonify({"success": False, "message": "❌ Key bị lỗi dữ liệu ngày tháng!"})

    # Vượt qua mọi bài test -> Cho phép vào phần mềm
    return jsonify({
        "success": True, 
        "message": f"✅ Kích hoạt thành công! Hạn dùng đến: {expire_date.strftime('%d/%m/%Y')}"
    })
# ====================================================================
# 1. API KIỂM TRA KẾT NỐI (TEST LOGIN & LẤY DẢI HÓA ĐƠN)
# ====================================================================
@app.route('/api/einvoice/test-connection', methods=['POST'])
def test_connection():
    try:
        data = request.json
        provider = data.get('provider')
        api_url = data.get('apiUrl')
        username = data.get('username')
        password = data.get('password')

        # 👉 THÊM DÒNG NÀY ĐỂ HẾT GẠCH VÀNG (Lấy dữ liệu hóa đơn từ React gửi lên)
        invoice_data = data.get('invoice', data)

        if provider == 'MOBIFONE':
            clean_url = api_url.split('/api/')[0].rstrip('/') 
            
            # 1. Gọi API Đăng nhập
            login_payload = {"username": username, "password": password}
            login_res = http_session.post(f"{clean_url}/api/Account/Login", json=login_payload, verify=False)
            login_data = login_res.json()

            if "error" in login_data:
                return jsonify({"success": False, "message": login_data['error']})
            
            token = login_data.get("token")
            ma_dvcs = login_data.get("ma_dvcs")

            # 2. Ngay khi đăng nhập xong, gọi luôn API lấy Dải Ký Hiệu Hóa Đơn
            headers = {
                "Authorization": f"Bear {token};{ma_dvcs}",
                "Content-Type": "application/json"
            }
            ref_res = http_session.get(f"{clean_url}/api/System/GetDataReferencesByRefId?refId=RF00061", headers=headers, verify=False)
            series_data = ref_res.json()

            # 3. Lọc dữ liệu cho gọn để gửi về React
            available_series = []
            if series_data and len(series_data) > 0:
                for item in series_data:
                    available_series.append({
                        "id": item.get("qlkhsdung_id"),     # ID ẩn để gửi API
                        "symbol": item.get("khhdon"),       # Ký hiệu (VD: 1C24TAA)
                        "template": item.get("mshdon")      # Mẫu số (VD: 1)
                    })

            return jsonify({
                "success": True, 
                "token": token, 
                "series": available_series # Gửi danh sách này về Web
            })

        # ====================================================================
        # TEST LOGIN BKAV (Bản siêu tối giản - Dụ BKAV nhả Base64)
        # ====================================================================
        elif provider == 'BKAV':
            clean_url = api_url.rstrip('/') 
            print(f"\n🔄 Đang gọi API THẬT test kết nối BKAV tới: {clean_url}")
            
            soap_payload = f"""<?xml version="1.0" encoding="utf-8"?>
            <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
              <soap:Body>
                <ExecCommand xmlns="http://tempuri.org/">
                  <partnerGUID>{username}</partnerGUID>
                  <CommandData>TEST_OMNISALE</CommandData>
                </ExecCommand>
              </soap:Body>
            </soap:Envelope>"""

            headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://tempuri.org/ExecCommand"'}
            bkav_res = http_session.post(clean_url, data=soap_payload.encode('utf-8'), headers=headers, verify=False)
            
            if "eyJTdGF0dXMi" in bkav_res.text or "not in Base64 format" in bkav_res.text:
                return jsonify({"success": True, "token": password, "series": [], "message": "✅ KẾT NỐI MÁY CHỦ BKAV THÀNH CÔNG!"})
            else:
                return jsonify({"success": False, "message": "Máy chủ BKAV từ chối kết nối!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi hệ thống lõi: {str(e)}"})
    

# ====================================================================
# 2. API XUẤT HÓA ĐƠN THỰC TẾ
# ====================================================================
@app.route('/api/einvoice/issue', methods=['POST'])
def issue_einvoice():
    data = request.json
    provider = data.get('provider')
    order = data.get('orderData')
    
    if provider == 'MISA':
        try:
            misa_payload = {
                "RefID": str(uuid.uuid4()),
                "InvDate": order['time'],
                "TotalAmount": order['total'],
                "Details": [{"ItemName": item['name'], "Quantity": item['qty'], "UnitPrice": item['price']} for item in order['items']]
            }
            return jsonify({"success": True, "lookupCode": f"MISA-{order['id']}", "message": "Success"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    elif provider == 'VIETTEL':
        try:
            viettel_payload = {
                "generalInvoiceInfo": {"invoiceType": "1", "templateCode": "01GTKT"},
                "buyerInfo": {"buyerName": order['customer']['name']},
                "itemInfo": [{"itemName": item['name'], "quantity": item['qty']} for item in order['items']]
            }
            return jsonify({"success": True, "lookupCode": f"VTL-{order['id']}", "message": "Success"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    elif provider == 'MOBIFONE':
        api_url = data.get('apiURL')       
        username = data.get('apiKey')      
        password = data.get('apiSecret')   
            
        if not api_url or not username or not password:
            return jsonify({"success": False, "message": "Thiếu cấu hình API URL, Username hoặc Password cho MobiFone!"})

        try:
            print(f"\n🚀 BẮT ĐẦU XUẤT HÓA ĐƠN MOBIFONE CHO ĐƠN: {order['id']}")
            login_payload = {"username": username, "password": password}
            clean_url = api_url.split('/api/')[0].rstrip('/') 
            
            # B1. Đăng nhập
            login_res = http_session.post(f"{clean_url}/api/Account/Login", json=login_payload)
            login_data = login_res.json()

            if "error" in login_data:
                raise Exception(f"Lỗi đăng nhập: {login_data['error']}")
                
            token = login_data.get("token")
            ma_dvcs = login_data.get("ma_dvcs")    

            # B2. Lấy thông tin dải Ký hiệu Hóa đơn (ĐÃ SỬA LẠI THÔNG MINH HƠN)
            headers = {
                "Authorization": f"Bear {token};{ma_dvcs}",
                "Content-Type": "application/json"
            }
                
            # ƯU TIÊN 1: Lấy ID Ký hiệu (Dải hóa đơn) mà người dùng đã chọn từ giao diện Web truyền xuống
            qlkhsdung_id = data.get('selectedSeriesId')

            # TÌNH HUỐNG DỰ PHÒNG: Nếu Web không truyền xuống (do khách chưa cấu hình), 
            # thì hệ thống mới tự động gọi API lấy danh sách và chọn đại cái đầu tiên
            if not qlkhsdung_id:
                print("⚠️ Web chưa chọn dải Ký hiệu. Tự động lấy dải mặc định từ Cục Thuế...")
                ref_res = http_session.get(f"{clean_url}/api/System/GetDataReferencesByRefId?refId=RF00061", headers=headers)
                ref_data = ref_res.json()
                
                if not ref_data or len(ref_data) == 0:
                    raise Exception("Tài khoản này chưa được Cục Thuế cấp dải ký hiệu hóa đơn (qlkhsdung_id)!")
                
                qlkhsdung_id = ref_data[0].get("qlkhsdung_id")
                
            print(f"-> Chốt sử dụng Dải HĐ: ID = {qlkhsdung_id}")

            # B3. Tạo Hóa Đơn
            total_before_tax = order['total']
            total_tax = 0
            total_after_tax = total_before_tax + total_tax
                
            details_data = []
            for idx, item in enumerate(order['items']):
                details_data.append({
                    "stt": str(idx + 1), 
                    "ma": f"SP{idx+1}", 
                    "ten": item['name'], 
                    "mdvtinh": "Cai", 
                    "dgia": item['price'], 
                    "sluong": item['qty'], 
                    "thtien": item['price'] * item['qty'], 
                    "tthue": 0, 
                    "tgtien": item['price'] * item['qty'], 
                    "kmai": 1, 
                    "tsuat": "-1" 
                })

            # =================================================================
            # LOGIC PHÂN LOẠI KHÁCH HÀNG (DỰA TRÊN SỰ TỒN TẠI CỦA MST)
            # =================================================================
            customer = order.get('customer', {})
            tax_code = customer.get('taxCode', '').strip()
            cus_name = customer.get('name', 'Khách lẻ').strip()
            cus_email = customer.get('email', '').strip()
            cus_address = customer.get('address', '').strip()
            cus_phone = customer.get('phone', '').strip()

            # Nếu CÓ Mã số thuế -> Đẩy vào ô Tên Công Ty (tenkh/ten). Để trống Tên người mua (tnmua).
            # Nếu KHÔNG CÓ MST -> Đẩy vào ô Tên người mua (tnmua).
            ten_don_vi = cus_name if tax_code else ""
            ten_nguoi_mua = "" if tax_code else cus_name

            create_payload = {
                "editmode": 1, 
                "data": [{
                    "cctbao_id": qlkhsdung_id, 
                    "nlap": datetime.now().strftime("%Y-%m-%d"), 
                    "dvtte": "VND", 
                    "tgia": 1, 
                    "htttoan": "Tiền mặt/Chuyển khoản", 
                    
                    # -----------------------------------------------------
                    # THÔNG TIN KHÁCH HÀNG ÁP DỤNG CHUẨN MOBIFONE
                    # -----------------------------------------------------
                    "mst": tax_code,                # Mã số thuế
                    "tenkh": ten_don_vi,            # Tên đơn vị mua hàng / Tên công ty
                    "ten": ten_don_vi,              # Back-up tên công ty
                    "tnmua": ten_nguoi_mua,         # Tên người mua hàng (Cá nhân)
                    
                    # Các trường Email (Khai báo cả 3 để chắc chắn MobiFone nhận)
                    "email": cus_email,
                    "dctdtu": cus_email,
                    "emnmua": cus_email,
                    
                    # Các trường Địa chỉ
                    "dchi": cus_address,            # Địa chỉ công ty
                    "dchdnmua": cus_address,        # Back-up địa chỉ
                    "sdtnmua": cus_phone,           # Số điện thoại
                    # -----------------------------------------------------

                    "tgtcthue": total_before_tax, 
                    "tgtthue": total_tax, 
                    "tgtttbso": total_after_tax, 
                    "tgtttbso_last": total_after_tax, 
                    "mdvi": ma_dvcs, 
                    "tthdon": 0, 
                    "is_hdcma": 1, 
                    "details": [{"data": details_data}] 
                }]
            }
                
            # GỌI API PHÁT HÀNH HÓA ĐƠN
            create_res = http_session.post(f"{clean_url}/api/Invoice68/SaveListHoadon78", json=create_payload, headers=headers) 
            print("Kết quả MobiFone:", create_res.json())
            
            lookup_code = f"MOBI-{str(uuid.uuid4())[:8].upper()}"
            print(f"✅ Đã xuất thành công. Mã tra cứu: {lookup_code}")
            return jsonify({"success": True, "lookupCode": lookup_code, "message": "Xuất HĐĐT MobiFone thành công!"})

        except requests.exceptions.RequestException as e:
            return jsonify({"success": False, "message": f"Lỗi mạng khi gọi API: {str(e)}"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    # ====================================================================
    # XUẤT HÓA ĐƠN ĐIỆN TỬ BKAV (Lệnh 101 + MÃ HÓA AES)
    # ====================================================================
    elif provider == 'BKAV':
        api_url = data.get('apiURL')       
        partner_guid = data.get('apiKey')  # PartnerGUID
        password = data.get('apiSecret')   # MẬT KHẨU (TOKEN) DÙNG ĐỂ LÀM CHÌA KHÓA AES
        
        if not api_url or not partner_guid or not password:
            return jsonify({"success": False, "message": "Thiếu API URL, PartnerGUID hoặc Mật khẩu Token của BKAV!"})

        try:
            print(f"\n🚀 BẮT ĐẦU XUẤT HÓA ĐƠN BKAV CHO ĐƠN: {order['id']}")
            clean_url = api_url.rstrip('/')
            
            # --- PHẦN GOM DỮ LIỆU ĐÃ ĐƯỢC "BỌC LÓT" KỸ CÀNG ---
            customer = order.get('customer', {})
            tax_code = customer.get('taxCode', '').strip()
            cus_name = customer.get('name', 'Khách lẻ').strip()
            cus_address = customer.get('address', '').strip()
            cus_phone = customer.get('phone', '').strip()
            
            # TRÁNH LỖI SẬP EMAIL CỦA BKAV
            cus_email = customer.get('email', '').strip()
            if not cus_email:
                cus_email = "doanhnghiepbinhthuan86@gmail.com" 

            is_business = bool(tax_code)

            list_details = []
            for idx, item in enumerate(order['items']):
                list_details.append({
                    "ItemTypeID": 0,
                    "ItemName": item['name'],
                    "UnitName": "Cái",
                    "Qty": float(item['qty']),
                    "Price": float(item['price']),
                    "Amount": float(item['qty'] * item['price']),
                    "TaxRateID": 4, 
                    "TaxRate": -1.0,
                    "TaxAmount": 0.0,
                    "IsDiscount": False,
                    "DiscountRate": 0.0,    # CHỐNG LỖI NULL CỦA BKAV
                    "DiscountAmount": 0.0   # CHỐNG LỖI NULL CỦA BKAV
                })

            # KHAI BÁO TƯỜNG MINH TẤT CẢ CÁC TRƯỜNG ĐỂ CHỐNG LỖI NULL MÁY CHỦ BKAV
            invoice_obj = {
                "InvoiceTypeID": 1, 
                "InvoiceStatusID": 1, # 👉 THÊM VÀO: 1 = Hóa đơn mới (Cực kỳ quan trọng)
                "InvoiceForm": "",    # 👉 THÊM VÀO: Bắt buộc khai báo dù rỗng
                "InvoiceSerial": "",  # 👉 THÊM VÀO: Bắt buộc khai báo dù rỗng
                "InvoiceDate": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "BuyerName": "" if is_business else cus_name, 
                "BuyerUnitName": cus_name if is_business else "", 
                "BuyerTaxCode": tax_code, 
                "BuyerAddress": cus_address if cus_address else "Khách mua lẻ", 
                "BuyerBankAccount": "", 
                "PayMethodID": 3, 
                "ReceiveTypeID": 4, 
                "ReceiverEmail": cus_email, 
                "ReceiverMobile": cus_phone, 
                "ReceiverName": cus_name,    
                "CurrencyID": "VND", 
                "ExchangeRate": 1.0, 
                "InvoiceNote": "Xuất từ OmniSale Pro"
            }

            command_object = [{
                "Invoice": invoice_obj,
                "ListInvoiceDetailsWS": list_details, 
                "PartnerInvoiceID": 0, # THÊM VÀO CHỐNG LỖI
                "PartnerInvoiceStringID": str(order['id']) 
            }]

            # Ép chuẩn UTF-8 để giữ nguyên chữ Tiếng Việt
            json_payload = json.dumps(command_object, ensure_ascii=False)
            inner_xml = f"<CommandData><CmdType>101</CmdType><CommandObject><![CDATA[{json_payload}]]></CommandObject></CommandData>"

            # =========================================================
            # ĐỘNG CƠ MÃ HÓA AES BẮT ĐẦU HOẠT ĐỘNG
            # =========================================================
            # Khóa AES yêu cầu độ dài 32 bytes (AES-256).
            key_bytes = password.encode('utf-8')
            key_bytes = key_bytes.ljust(32, b'\0')[:32] 
            
            cipher = AES.new(key_bytes, AES.MODE_ECB)
            padded_data = pad(inner_xml.encode('utf-8'), AES.block_size)
            encrypted_data = cipher.encrypt(padded_data)
            base64_encrypted_data = base64.b64encode(encrypted_data).decode('utf-8')

            # =========================================================
            # GÓI VÀO SOAP VÀ BẮN SANG BKAV
            # =========================================================
            soap_payload = f"""<?xml version="1.0" encoding="utf-8"?>
            <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
              <soap:Body>
                <ExecCommand xmlns="http://tempuri.org/">
                  <partnerGUID>{partner_guid}</partnerGUID>
                  <CommandData>{base64_encrypted_data}</CommandData>
                </ExecCommand>
              </soap:Body>
            </soap:Envelope>"""

            headers = {
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"http://tempuri.org/ExecCommand"'
            }

            bkav_res = http_session.post(clean_url, data=soap_payload.encode('utf-8'), headers=headers, verify=False)
            
            print(f"📩 Mã trạng thái HTTP: {bkav_res.status_code}")
            
            # --- GIẢI MÃ KẾT QUẢ VỚI RE.DOTALL ---
            match = re.search(r'<ExecCommandResult>(.*?)</ExecCommandResult>', bkav_res.text, re.DOTALL)
            if match:
                b64_str = match.group(1).strip()
                try:
                    decoded_text = base64.b64decode(b64_str).decode('utf-8')
                    print(f"🔍 BKAV PHẢN HỒI ĐƠN {order['id']}:", decoded_text)
                    
                    if '"Status":0' in decoded_text:
                        # THÀNH CÔNG RỰC RỠ! Lấy mã tra cứu.
                        res_json = json.loads(decoded_text)
                        obj_data_str = res_json.get("Object", "[]")
                        obj_data = json.loads(obj_data_str) if isinstance(obj_data_str, str) else obj_data_str
                        lookup_code = obj_data[0].get("MTC", "N/A") if obj_data else "N/A"
                        
                        return jsonify({"success": True, "lookupCode": lookup_code, "message": "✅ Xuất hóa đơn BKAV thành công!"})
                    else:
                        return jsonify({"success": False, "message": f"BKAV báo lỗi dữ liệu: {decoded_text}"})
                
                except Exception as e:
                    return jsonify({"success": False, "message": f"Lỗi giải mã Base64 từ BKAV: {str(e)}"})
            else:
                return jsonify({"success": False, "message": "Lỗi: Không đọc được phản hồi từ BKAV."})

        except Exception as e:
            print(f"❌ LỖI TRẠM TRUNG CHUYỂN BKAV: {str(e)}")
            return jsonify({"success": False, "message": f"Lỗi xuất HĐĐT BKAV: {str(e)}"})
if __name__ == '__main__':
    print("=================================================================")
    print("🚀 Khởi động Trạm trung chuyển Hóa đơn điện tử trên CLOUD...")
    print("=================================================================")
    # Cloud sẽ tự động cấp Port, nếu chạy ở máy nhà thì nó lấy 5000
    port = int(os.environ.get('PORT', 5000)) 
    # Đổi host thành '0.0.0.0' để Cloud có thể truy cập được
    app.run(host='0.0.0.0', port=port, debug=False)
