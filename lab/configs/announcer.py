import sys
import time

time.sleep(5)

# Анонсируем с community 65030:220 (excellent - LOCAL_PREF 220)
sys.stdout.write("announce route 172.16.1.0/24 next-hop 10.0.44.2 community 65030:220\n")
sys.stdout.flush()

while True:
    time.sleep(60)
