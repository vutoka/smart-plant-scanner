# ===== scan_sync.py (Raspberry Pi) v2.1 =====
import os, re, csv, time, subprocess, sys
from datetime import datetime
from collections import Counter

import serial, serial.tools.list_ports

STEPS_PER_REV = 4096
NUM_POSITIONS = 12
SETTLE_SEC = 0.25
MOVE_TIMEOUT = 60.0
SER_BAUD = 115200
EST_STEP_DELAY_S = 0.003
UNWIND_AFTER_SPIN = True

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_PATH = os.path.join(ROOT, "slika_1.jpg")
PREDICT_SCRIPT = os.path.join(ROOT, "predict_tflite.py")
LOG_PATH = os.path.join(ROOT, "scan_log.csv")
SUMMARY_PATH = os.path.join(ROOT, "scan_summary.csv")

def find_serial_port():
    for c in ["/dev/ttyUSB0","/dev/ttyACM0"]:
        if os.path.exists(c): return c
    for p in serial.tools.list_ports.comports():
        if ("USB" in p.device) or ("ACM" in p.device):
            return p.device
    raise RuntimeError("Nema serijskog porta.")

def open_serial():
    ser = serial.Serial(find_serial_port(), SER_BAUD, timeout=0.1)
    time.sleep(0.5)
    ser.reset_input_buffer(); ser.reset_output_buffer()
    return ser

def wait_ready(ser, timeout=6.0):
    t0=time.time()
    while time.time()-t0<timeout:
        if ser.in_waiting:
            line=ser.readline().decode(errors="ignore").strip()
            if line: print("SER:", line)
            if "READY" in line: return True
    return False

def send_cmd(ser, cmd, wait_done=True, timeout=MOVE_TIMEOUT):
    ser.write((cmd.strip()+"\r\n").encode())
    t0=time.time()
    while True:
        if wait_done and (time.time()-t0)>timeout:
            raise TimeoutError(f"Timeout čekajući DONE za '{cmd}'")
        if ser.in_waiting:
            resp=ser.readline().decode(errors="ignore").strip()
            if not resp: continue
            # print("SER:", resp)
            if resp.startswith("DONE"): return resp
            if resp.startswith("ERR"): raise RuntimeError(resp)
        if not wait_done: return "OK"

def capture_image(path):
    r = subprocess.run([
        "libcamera-still","--immediate","--nopreview","-n",
        "--width","1280","--height","720","--timeout","1","-o",path
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode!=0:
        raise RuntimeError("libcamera-still fail: "+r.stderr.decode(errors="ignore"))

def run_prediction():
    r = subprocess.run(["python3", PREDICT_SCRIPT], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = r.stdout + "\n" + r.stderr
    m = re.search(r"\b(GR|GP|PH)\b", out)
    return (m.group(1) if m else "UNK"), out.strip()

def parse_sensors(ser):
    ser.write(b"GET_SENSORS\r\n")
    t0=time.time(); line=None
    while time.time()-t0<1.5:
        if ser.in_waiting:
            s=ser.readline().decode(errors="ignore").strip()
            if s.startswith("SENS"): line=s; break
    T=RH=SOIL=None
    if line:
        mt=re.search(r"T=([0-9\.\-NaN]+)", line)
        mh=re.search(r"RH=([0-9\.\-NaN]+)", line)
        ms=re.search(r"SOIL=([0-9]+)", line)
        if mt: T=mt.group(1)
        if mh: RH=mh.group(1)
        if ms: SOIL=ms.group(1)
    return T,RH,SOIL

def led_off(ser):   return send_cmd(ser, "LED OFF")
def led_on(ser,pwm=255): return send_cmd(ser, f"LED ON {int(pwm)}")
def led_blink(ser, period_ms=1000, duty=50, pwm=255):
    return send_cmd(ser, f"LED BLINK {int(period_ms)} {int(duty)} {int(pwm)}")

def majority_vote(labels):
    filt=[x for x in labels if x and x!="UNK"]
    if not filt: return "UNK",{},0.0
    c=Counter(filt); most,cnt=c.most_common(1)[0]; tot=sum(c.values())
    return most, dict(c), (cnt/tot if tot else 0.0)

def write_summary(ts, pass_name, labels, sensors_at_decision=None):
    label, counts, conf = majority_vote(labels)
    newf = not os.path.exists(SUMMARY_PATH)
    with open(SUMMARY_PATH,"a",newline="") as f:
        w=csv.writer(f)
        if newf: w.writerow(["ts","pass","majority_label","confidence","counts_json","T","RH","SOIL"])
        counts_str=";".join([f"{k}:{v}" for k,v in sorted(counts.items())])
        T=RH=SOIL=("","","")
        if sensors_at_decision: T, RH, SOIL = sensors_at_decision
        w.writerow([ts, pass_name, label, f"{conf:.3f}", counts_str, T, RH, SOIL])
    print(f"[{pass_name} SUMMARY] label={label} conf={conf:.2f} counts={counts} sensors={sensors_at_decision}")
    return label, conf, counts

def estimate_timeout_for_steps(steps):
    est = abs(steps)*EST_STEP_DELAY_S
    return max(15.0, est*1.5 + 5.0)

def spin_revs(ser, revs, unwind=UNWIND_AFTER_SPIN):
    steps=int(round(revs*STEPS_PER_REV))
    if steps==0: return
    tmo=estimate_timeout_for_steps(steps)
    print(f"== ACTION: Spin +{revs} revs ({steps} steps) ==")
    send_cmd(ser, f"STEP {steps}", timeout=tmo)
    time.sleep(0.2)
    if unwind:
        print(f"== ACTION: Unwind -{revs} revs ({-steps} steps) ==")
        send_cmd(ser, f"STEP {-steps}", timeout=tmo)
        time.sleep(0.2)
    print("== ACTION: Done ==")

def apply_phase_action(ser, phase_label):
    # LED po fazi + ispis senzora; spin ostaje kao u v1.2 (demo)
    if phase_label=="GR":
        print("Phase=GR → LED OFF, motor stop. Čitam senzore…")
        led_off(ser)
        T,RH,SOIL = parse_sensors(ser)
        print(f"SENSORS (GR): T={T} °C  RH={RH}%  SOIL={SOIL}")
        # no spin
    elif phase_label=="GP":
        print("Phase=GP → LED BLINK 1Hz 50%, spin 1 rev (sa odmotavanjem). Čitam senzore…")
        led_blink(ser, period_ms=1000, duty=50, pwm=255)
        T,RH,SOIL = parse_sensors(ser)
        print(f"SENSORS (GP): T={T} °C  RH={RH}%  SOIL={SOIL}")
        spin_revs(ser, 1.0, unwind=True)
    elif phase_label=="PH":
        print("Phase=PH → LED ON 100%, spin 2 revs (sa odmotavanjem). Čitam senzore…")
        led_on(ser, 255)
        T,RH,SOIL = parse_sensors(ser)
        print(f"SENSORS (PH): T={T} °C  RH={RH}%  SOIL={SOIL}")
        spin_revs(ser, 2.0, unwind=True)
    else:
        print(f"Phase={phase_label} → unknown, LED OFF (safety).")
        led_off(ser)

def main():
    ser = open_serial()
    print("SERIAL opened. Waiting READY...")
    wait_ready(ser, 6.0)

    print("HOME..."); send_cmd(ser, "HOME")

    step_inc = STEPS_PER_REV // NUM_POSITIONS
    positions = [i*step_inc for i in range(NUM_POSITIONS)]

    newf = not os.path.exists(LOG_PATH)
    logf=open(LOG_PATH,"a",newline=""); w=csv.writer(logf)
    if newf: w.writerow(["ts","pass","pos_steps","label","T","RH","SOIL","move_ms","infer_ms"])

    # forward
    forward_labels=[]
    for p in positions:
        t0=time.time(); send_cmd(ser,f"MOVE_ABS {p}"); move_ms=int((time.time()-t0)*1000)
        time.sleep(SETTLE_SEC); capture_image(IMG_PATH)
        ti=time.time(); label,_=run_prediction(); infer_ms=int((time.time()-ti)*1000)
        forward_labels.append(label)
        T,RH,SOIL=parse_sensors(ser)
        w.writerow([datetime.now().isoformat(),"forward",p,label,T,RH,SOIL,move_ms,infer_ms]); logf.flush()
        print(f"pos={p} -> {label} | move={move_ms}ms infer={infer_ms}ms")
    write_summary(datetime.now().isoformat(),"forward",forward_labels)

    # backward
    backward_labels=[]
    for p in reversed(positions):
        t0=time.time(); send_cmd(ser,f"MOVE_ABS {p}"); move_ms=int((time.time()-t0)*1000)
        time.sleep(SETTLE_SEC); capture_image(IMG_PATH)
        ti=time.time(); label,_=run_prediction(); infer_ms=int((time.time()-ti)*1000)
        backward_labels.append(label)
        T,RH,SOIL=parse_sensors(ser)
        w.writerow([datetime.now().isoformat(),"backward",p,label,T,RH,SOIL,move_ms,infer_ms]); logf.flush()
        print(f"[back] pos={p} -> {label} | move={move_ms}ms infer={infer_ms}ms")
    write_summary(datetime.now().isoformat(),"backward",backward_labels)

    # combined + LED/sensors + spin
    all_labels = forward_labels + backward_labels
    # pročitaj senzore baš u trenutku odluke
    sensors_now = parse_sensors(ser)
    write_summary(datetime.now().isoformat(),"combined", all_labels, sensors_at_decision=sensors_now)
    maj,counts,conf = majority_vote(all_labels)
    print(f"[COMBINED] phase={maj} conf={conf:.2f} counts={counts} sensors={sensors_now}")

    apply_phase_action(ser, maj)

    logf.close()
    print("Done. Logs:", LOG_PATH, "| Summary:", SUMMARY_PATH)

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print("Greška:", e)
        sys.exit(1)
