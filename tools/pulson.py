#!/usr/bin/env python3
"""
pulson.py — klient chmury PulsON Alarm (MQTT/TLS, reverse-engineered z aplikacji).
Czysty stdlib. Działa też w kontenerze Home Assistant (python3).

KONFIGURACJA (dane z kodu QR: "1;HOST;PORT;PIN;SYSTEM_ID"):
    export PULSON_HOST=solid.pulsonalarm.pl
    export PULSON_SID=0011223344556677889900aa
    export PULSON_PIN=xxxx
  (albo flagi --host --sid --pin)

KOMENDY:
    status [sek]      migawka: bieżący stan partycji/linii/wyjść (domyślnie 10s)
    watch  [sek]      dashboard na żywo, odświeża się przy każdej zmianie (domyślnie 3600s)
    arm     <part>    uzbrój (away)
    night   <part>    uzbrój nocne
    disarm  <part>    rozbrój
    block   <linia>   zablokuj linię
    unblock <linia>   odblokuj linię
    output  <id> on|off   sterowanie wyjściem PGM
    panic   --force   SYGNAŁ NAPADU (alarmuje stację monitorowania!)

PRZYKŁADY:
    python3 pulson.py status
    python3 pulson.py watch
    python3 pulson.py arm 1
    python3 pulson.py output 1 on
"""
import sys, os, ssl, socket, struct, hashlib, time, select, argparse

_UP="fqCxoqb7ys6wX582fza0"; _US="R9DmiPnoHEBVw9B39evU"
_PP="oh2Zp9BVs7JlrP5q1Ik2"; _PS="cX0EyPCvL5ZjEaTBIwhe"
_md5=lambda s: hashlib.md5(s.encode()).hexdigest()
def mqtt_user(sid,pin): return f"{sid}_"+_md5(f"{_UP}{pin}{_US}")
def mqtt_pass(sid,pin): return _md5(f"{_PP}{sid}_{pin}{_PS}")

# dekodowanie stanów (z reverse libpulson.so)
PART={0:"ROZBROJONY",1:"UZBROJONY",2:"UZBROJONY (nocny)",3:"czas na wejście",4:"czas na wyjście",
 5:"⚠ ALARM WŁAMANIE",6:"⚠ ALARM POŻAR",7:"⚠ ALARM GAZ",8:"⚠ ALARM CZAD",9:"⚠ ALARM MEDYCZNY",
 10:"⚠ alarm zdefiniowany",11:"⚠ SABOTAŻ",12:"⚠ ALARM ZALANIE",13:"⚠ ALARM TEMPERATURA",
 14:"czas na wejście (noc)",15:"czas na wyjście (noc)",16:"⚠ ALARM PANIKA",17:"⚠ ALARM NAPAD",
 18:"⚠ sabotaż linii",19:"alarm w pamięci"}
LINE={0:"—",1:"zamknięta",2:"OTWARTA",3:"⚠ sabotaż",4:"⚠ usterka"}

C_G="\033[32m"; C_R="\033[31m"; C_Y="\033[33m"; C_B="\033[1m"; C_0="\033[0m"; C_D="\033[2m"
def _color(): return sys.stdout.isatty()

# ---------- MQTT 3.1 (jak aplikacja) ----------
def _rl(n):
    o=bytearray()
    while True:
        b=n%128; n//=128; o.append(b|0x80 if n else b)
        if not n: return bytes(o)
def _s(x): b=x.encode(); return struct.pack("!H",len(b))+b
def _recv(sock):
    h=sock.recv(1)
    if not h: return None,None
    typ=h[0]; mult=1; ln=0
    while True:
        c=sock.recv(1)
        if not c: return None,None
        c=c[0]; ln+=(c&0x7f)*mult; mult*=128
        if not c&0x80: break
    body=b""
    while len(body)<ln:
        ch=sock.recv(ln-len(body))
        if not ch: break
        body+=ch
    return typ>>4, body

PART_FIELDS=["name","status","active","night_mode","alarm","ready","exit_time"]
LINE_FIELDS=["name","status","block","block_enable"]
OUT_FIELDS =["name","status"]

class Pulson:
    ROOTS=lambda self:[f"system/{self.sid}/users/{self.user}/#", f"system/{self.sid}/#", f"system/{self.sid}/programming"]
    def __init__(self, host, sid, pin):
        self.host=host; self.sid=sid; self.pin=pin; self.user=mqtt_user(sid,pin); self.sock=None
    def connect(self):
        ctx=ssl.create_default_context()
        try:
            self.sock=ctx.wrap_socket(socket.create_connection((self.host,8883),timeout=10),server_hostname=self.host)
        except ssl.SSLError:
            ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
            self.sock=ctx.wrap_socket(socket.create_connection((self.host,8883),timeout=10),server_hostname=self.host)
        cid="pulson-cli-%d"%(int(time.time())%100000)
        var=_s("MQIsdp")+bytes([3,0x02|0x80|0x40])+struct.pack("!H",10)
        body=var+_s(cid)+_s(self.user)+_s(mqtt_pass(self.sid,self.pin))
        self.sock.send(bytes([0x10])+_rl(len(body))+body)
        t,b=_recv(self.sock)
        rc=b[1] if (t==2 and len(b)>1) else 99
        if rc!=0: raise RuntimeError(f"CONNACK rc={rc} ("+{4:'zły login/hasło',5:'brak autoryzacji'}.get(rc,'błąd')+")")
        return self
    _pid=1
    def subscribe(self, tp):
        self._pid+=1
        pkt=struct.pack("!H",self._pid)+_s(tp)+b"\0"
        self.sock.send(bytes([0x82])+_rl(len(pkt))+pkt)
    def subscribe_all(self):
        # tylko WYSYŁAMY subskrypcje; SUBACK-i i retained obrabia pętla collect()
        for tp in self.ROOTS(): self.subscribe(tp)
    def subscribe_granular(self, module, ids):
        """Dosubskrybuj DOKŁADNE topiki liści per-element — obie struktury (z/bez users)."""
        fields={"partitions":PART_FIELDS,"inputs":LINE_FIELDS,"outputs":OUT_FIELDS}[module]
        bases=[f"system/{self.sid}/users/{self.user}/", f"system/{self.sid}/"]
        for base in bases:
            for _id in ids:
                for f in fields: self.subscribe(f"{base}{module}/{_id}/{f}")
    def publish(self, subtopic, value):
        topic=f"system/{self.sid}/{subtopic}"; payload=f"{self.pin}/{value}"
        body=struct.pack("!H",len(topic.encode()))+topic.encode()+payload.encode()
        self.sock.send(bytes([0x30])+_rl(len(body))+body)
    def ping(self): self.sock.send(bytes([0xc0,0x00]))
    def close(self):
        try: self.sock.send(bytes([0xe0,0x00])); self.sock.close()
        except Exception: pass

# ---------- model stanu z przychodzących wiadomości ----------
class State:
    def __init__(self):
        self.part={}; self.line={}; self.out={}; self.perm=None; self.raw={}; self.online={}; self.programming=None
    def feed(self, topic, payload):
        seg=topic.split("/")
        try: seg=seg[seg.index("users")+2:]
        except ValueError: seg=seg[2:]   # po system/{sid}/
        if not seg: return
        mod=seg[0]
        if mod=="online" and len(seg)==2:
            self.online[seg[1]]=payload; return
        if mod=="programming":
            self.programming = ("1" in str(payload).split(":")[0]); return
        if len(seg)==1:                                   # listy / permissions
            if mod=="permissions": self.perm=payload
            self.raw[mod]=payload
            if mod in ("partitions","inputs","outputs"):
                tgt={"partitions":self.part,"inputs":self.line,"outputs":self.out}[mod]
                for x in payload.split(","):
                    x=x.strip()
                    if x: tgt.setdefault(x,{})
            return
        if len(seg)>=3:
            _id,field,val=seg[1],seg[2],payload
            tgt={"partitions":self.part,"inputs":self.line,"outputs":self.out}.get(mod)
            if tgt is not None: tgt.setdefault(_id,{})[field]=val
        elif len(seg)==2:
            _id=seg[1]
            tgt={"partitions":self.part,"inputs":self.line,"outputs":self.out}.get(mod)
            if tgt is not None: tgt.setdefault(_id,{})["_"]=payload

def _i(d,*keys):
    for k in keys:
        v=d.get(k)
        if v is not None and str(v).lstrip("-").isdigit(): return int(v)
    return None

def _b(d,*keys):
    """Bool z pola które bywa 'true'/'false' albo '1'/'0'."""
    for k in keys:
        v=d.get(k)
        if v is None: continue
        return str(v).strip().lower() in ("1","true","on","yes")
    return None

def render(st):
    c=_color()
    def col(x,code): return f"{code}{x}{C_0}" if c else x
    L=[]
    L.append(col("═"*44,C_D))
    L.append(col(f" PulsON — {time.strftime('%H:%M:%S')}",C_B))
    L.append(col("═"*44,C_D))
    # PARTYCJE
    L.append(col("PARTYCJE:",C_B))
    if not st.part: L.append("  (brak danych — stan nie nadszedł)")
    for pid in sorted(st.part, key=lambda x:int(x) if x.isdigit() else 0):
        d=st.part[pid]; s=_i(d,"status","state","_","newState")
        name=d.get("name",""); txt=PART.get(s,f"? ({s})") if s is not None else "?"
        code=C_G if s==0 else (C_R if (s is not None and 5<=s<=19 and s not in(14,15,19)) else C_Y)
        extra=[]
        if _b(d,"alarm"): extra.append(col("ALARM",C_R))
        rdy=_b(d,"ready","isReadyToArm")
        if rdy is not None: extra.append("gotowa" if rdy else col("niegotowa",C_Y))
        # exit_time pokazuj tylko podczas odliczania czasu na wyjście (status 4/15)
        if s in (4,15):
            et=_i(d,"exit_time")
            if et: extra.append(col(f"wyjście {et}s",C_Y))
        ex=(" · "+", ".join(extra)) if extra else ""
        L.append(f"  #{pid} {name:<10} {col(txt,code)}{ex}")
    # LINIE
    L.append(col("LINIE:",C_B))
    if not st.line: L.append("  (brak)")
    for lid in sorted(st.line, key=lambda x:int(x) if x.isdigit() else 0):
        d=st.line[lid]; s=_i(d,"status","state","_"); name=d.get("name","")
        txt=LINE.get(s,f"?({s})") if s is not None else "?"
        code=C_G if s==1 else (C_Y if s in(2,) else (C_R if s in(3,4) else C_D))
        blk=""
        if _b(d,"block","block_set"): blk=col(" [ZABLOKOWANA]",C_Y)
        L.append(f"  #{lid} {name:<10} {col(txt,code)}{blk}")
    # WYJŚCIA
    if st.out:
        L.append(col("WYJŚCIA:",C_B))
        for oid in sorted(st.out, key=lambda x:int(x) if x.isdigit() else 0):
            d=st.out[oid]; s=_i(d,"state","status","_"); name=d.get("name","")
            txt=col("ON",C_G) if s==1 else ("OFF" if s==0 else f"?({s})")
            L.append(f"  #{oid} {name:<10} {txt}")
    if st.online:
        def onl(v):
            b=str(v).lower() in("1","true"); return col("online",C_G) if b else col("OFFLINE",C_R)
        parts=[f"{k}={onl(v)}" for k,v in st.online.items()]
        L.append(col("MODUŁY: ",C_B)+"  ".join(parts))
    if st.programming:
        L.append(col("⚠ TRYB PROGRAMOWANIA (instalator)",C_Y))
    if st.perm is not None:
        L.append(col(f"UPRAWNIENIA: {st.perm}",C_D))
    return "\n".join(L)

def _module_of(topic):
    """Zwraca 'partitions'/'inputs'/'outputs' jeśli topic to GOŁA lista modułu, inaczej None."""
    seg=topic.split("/")
    try: seg=seg[seg.index("users")+2:]
    except ValueError: seg=seg[2:]
    return seg[0] if len(seg)==1 and seg[0] in ("partitions","inputs","outputs") else None

def collect(pc, secs, live=False):
    st=State(); end=time.time()+secs; lp=time.time(); dirty=True
    subscribed=set()
    if live and _color(): sys.stdout.write("\033[2J")
    while time.time()<end:
        r,_,_=select.select([pc.sock],[],[],1.0)
        if time.time()-lp>7: pc.ping(); lp=time.time()
        if live and dirty:
            if _color(): sys.stdout.write("\033[H\033[2J")
            print(render(st)); print(("\n"+C_D+"(watch — Ctrl-C by wyjść)"+C_0) if _color() else "\n(watch)")
            dirty=False
        if not r: continue
        t,b=_recv(pc.sock)
        if t is None: break
        if t==3:
            tl=struct.unpack("!H",b[:2])[0]; tp=b[2:2+tl].decode(errors="replace"); pl=b[2+tl:]
            try: val=pl.decode()
            except Exception: val=pl.hex()
            if os.environ.get("PULSON_DEBUG"): print(f"  [raw] {tp} = {val!r}")
            st.feed(tp,val); dirty=True
            # gdy przyszła lista modułu -> dosubskrybuj granularne liście (wyzwala push stanu)
            mod=_module_of(tp)
            if mod and mod not in subscribed:
                subscribed.add(mod)
                ids=[x.strip() for x in val.split(",") if x.strip()]
                pc.subscribe_granular(mod, ids)
    return st

def main():
    ap=argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?", default="status")
    ap.add_argument("a1", nargs="?"); ap.add_argument("a2", nargs="?")
    ap.add_argument("--host",default=os.environ.get("PULSON_HOST"))
    ap.add_argument("--sid", default=os.environ.get("PULSON_SID"))
    ap.add_argument("--pin", default=os.environ.get("PULSON_PIN"))
    ap.add_argument("--force",action="store_true")
    ap.add_argument("-h","--help",action="store_true")
    a=ap.parse_args()
    if a.help or not(a.host and a.sid and a.pin):
        print(__doc__)
        if not a.help: print("BŁĄD: brak host/sid/pin (env PULSON_* albo --host/--sid/--pin)")
        return
    pc=Pulson(a.host,a.sid,a.pin)
    try: pc.connect(); pc.subscribe_all()
    except Exception as e: print("Połączenie nieudane:",e); return
    try:
        c=a.cmd
        if c=="status":
            secs=int(a.a1) if a.a1 and a.a1.isdigit() else 10
            print(f"Zbieram stan {secs}s...\n")
            st=collect(pc,secs); print(render(st))
        elif c=="watch":
            collect(pc, int(a.a1) if a.a1 and a.a1.isdigit() else 3600, live=True)
        elif c in ("arm","night","disarm"):
            if not a.a1: print("Podaj numer partycji, np: arm 1"); return
            verb,val={"arm":("set_arm","1"),"night":("set_arm","2"),"disarm":("set_disarm","0")}[c]
            pc.publish(f"partitions/{a.a1}/{verb}",val); print(f"Wysłano: {c} partycja {a.a1}. Stan za chwilę...\n")
            st=collect(pc,8); print(render(st))
        elif c in ("block","unblock"):
            if not a.a1: print("Podaj numer linii"); return
            pc.publish(f"inputs/{a.a1}/block_set","1" if c=="block" else "0"); print(f"Wysłano: {c} linia {a.a1}")
            st=collect(pc,5); print(render(st))
        elif c=="output":
            if not(a.a1 and a.a2 in("on","off")): print("Użycie: output <id> on|off"); return
            pc.publish(f"outputs/{a.a1}/set","1" if a.a2=="on" else "0"); print(f"Wysłano: wyjście {a.a1} {a.a2}")
            st=collect(pc,5); print(render(st))
        elif c=="raw":
            # DIAGNOSTYKA: jedna sesja, surowe pakiety, WYMUSZONA zmiana stanu (arm->disarm).
            import time as _t
            def drain(sec,lp):
                n=0; end=_t.time()+sec
                while _t.time()<end:
                    r,_,_=select.select([pc.sock],[],[],1.0)
                    if _t.time()-lp[0]>7: pc.ping(); lp[0]=_t.time()
                    if not r: continue
                    t,b=_recv(pc.sock)
                    if t is None: print("(rozłączony przez broker!)"); return -1
                    if t==3:
                        tl=struct.unpack("!H",b[:2])[0]; tp=b[2:2+tl].decode(errors="replace"); pl=b[2+tl:]
                        printable=all(32<=x<127 or x in(9,10,13) for x in pl)
                        print(f"{_t.strftime('%H:%M:%S')}  {tp}")
                        print(f"           = {pl.decode(errors='replace')!r}" if printable else f"           = HEX {pl.hex()}")
                        n+=1
                return n
            print("RAW — zamknij apkę na telefonie. Wymuszę zmianę: ARM(1) → 5s → DISARM(1) → 15s.")
            print("(uzbrojenie trwa tylko 5s — dużo poniżej czasu na wyjście)\n")
            lp=[_t.time()]; total=0
            _t.sleep(1.0)
            print(">> ARM partycja 1"); pc.publish("partitions/1/set_arm","1")
            r=drain(5,lp); total+= (r if r>0 else 0)
            print(">> DISARM partycja 1"); pc.publish("partitions/1/set_disarm","0")
            r=drain(15,lp); total+= (r if r>0 else 0)
            print(f"\nRAW: {total} wiadomości (poza startowymi listami).")
        elif c=="panic":
            if not a.force:
                print("STOP: 'panic' wysyła sygnał NAPADU do stacji monitorowania (może wezwać ochronę/policję).")
                print("Jeśli na pewno: python3 pulson.py panic --force"); return
            pc.publish("panic_alarm","1"); print("!!! WYSŁANO SYGNAŁ NAPADU !!!")
        else:
            print("Nieznana komenda:",c); print(__doc__)
    except KeyboardInterrupt:
        print()
    finally:
        pc.close()

if __name__=="__main__":
    main()
