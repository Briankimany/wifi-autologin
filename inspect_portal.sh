#!/usr/bin/env bash
# Debug aid: fetch the captive-portal management login page and dump the JS
# logic that drives the voucher login (#btn-submit / #loginform).
#
# Fill these in for your device/network before running:
#   MAC=aa:bb:cc:dd:ee:ff IP=10.0.0.2 HOTSPOT=my-hotspot ./inspect_portal.sh
set -e
cd /tmp

MAC="${MAC:-}"
IP="${IP:-}"
HOTSPOT="${HOTSPOT:-}"

echo "== fetching management login page =="
curl -s -m 25 -G 'http://c.netpap.co.ke/management/login/' \
  -d "mac=$MAC" \
  -d "ip=$IP" \
  -d 'username=' \
  -d "hotspot=$HOTSPOT" \
  -d 'linklogin=http://namonet.wifi/login' \
  -d 'linkorig=' \
  -d 'error=' \
  -d 'chapid=' \
  -d 'chapchallenge=' \
  -d 'linkloginonly=http://namonet.wifi/login' \
  -d 'linkorigesc=' \
  -d "macesc=$MAC" \
  -o mgmt.html -w "http=%{http_code} size=%{size_download}\n"

echo "== script/src tags =="
grep -o 'src="[^"]*"' mgmt.html | sort -u

echo "== references to login elements =="
grep -oE '.{60}(btn-submit|loginform|#login|voucher|chapid|chapchallenge).{80}' mgmt.html | head -40

echo "== inline script blocks (relevant lines) =="
awk '/<script/{f=1;next} /<\/script>/{f=0} f' mgmt.html | grep -nE 'submit|login|voucher|ajax|password|form' | head -60
