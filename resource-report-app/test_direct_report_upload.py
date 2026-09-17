import urllib.request
import os

path = r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report\Resource Utilization Report.xlsx"
with open(path, 'rb') as f:
    file_bytes = f.read()

boundary = "----WebKitFormBoundaryUploadTest"
part_header = (
    f"--{boundary}\r\n"
    f"Content-Disposition: form-data; name=\"files\"; filename=\"Resource Utilization Report.xlsx\"\r\n"
    f"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
).encode('utf-8')
part_footer = f"\r\n--{boundary}--\r\n".encode('utf-8')
body = part_header + file_bytes + part_footer

req = urllib.request.Request(
    'http://127.0.0.1:8000/upload',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
)
opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
resp = opener.open(req)
print('Response code:', resp.status)
print('Final URL:', resp.geturl())
content = resp.read().decode('utf-8')
print('Team Resource Utilization in content:', 'Team Resource Utilization Report' in content)
print('August-2026 in content:', 'August-2026' in content)
print('843.8 in content:', ('843.75' in content or '843.8' in content))
