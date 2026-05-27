# -*- coding: utf-8 -*-
"""
量化选股系统 v7 — 可视化仪表盘
启动后在浏览器中打开 http://localhost:8050 查看
"""
import http.server
import json
import os
import sys
import io
import webbrowser
import pandas as pd
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REC_LOG = os.path.join(BASE_DIR, 'recommendation_log.csv')
RESULT_CSV = os.path.join(BASE_DIR, 'pullback_analysis_result.csv')

def load_data():
    data = {'recommendations': [], 'scores': [], 'stats': {}}
    if os.path.exists(REC_LOG):
        df = pd.read_csv(REC_LOG, encoding='utf-8-sig', dtype={'代码': str})
        df['代码'] = df['代码'].astype(str).str.zfill(6)
        data['recommendations'] = df.to_dict(orient='records')
    if os.path.exists(RESULT_CSV):
        df2 = pd.read_csv(RESULT_CSV, encoding='utf-8-sig', dtype={'代码': str})
        df2['代码'] = df2['代码'].astype(str).str.zfill(6)
        top = df2.head(30)
        cols = [c for c in ['代码','名称','板块','出现天数','上涨占比','10日累涨',
                '频率分','胜率分','回调分','动量分','排名分','趋势分','板块分',
                '资金分','消息分','流动性分','概念分','市场环境分','日内分',
                '综合评分','理由','风险标记'] if c in top.columns]
        data['scores'] = top[cols].fillna('').to_dict(orient='records')
    return data

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>量化选股仪表盘 v7</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#0a0e17;color:#e0e6ed;min-height:100vh}
.hdr{background:linear-gradient(135deg,#0f1923,#1a2332);padding:20px 32px;
  border-bottom:1px solid rgba(99,179,237,.15);display:flex;align-items:center;justify-content:space-between}
.hdr h1{font-size:20px;font-weight:700;background:linear-gradient(90deg,#63b3ed,#b794f4);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr .ts{font-size:13px;color:#a0aec0}
.wrap{max-width:1400px;margin:0 auto;padding:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:24px}
.card{background:linear-gradient(145deg,#141c2b,#1a2435);border:1px solid rgba(99,179,237,.1);
  border-radius:10px;padding:18px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:linear-gradient(90deg,#63b3ed,#b794f4)}
.card .lb{font-size:11px;color:#718096;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.card .vl{font-size:26px;font-weight:700;color:#fff}
.card .sb{font-size:11px;color:#a0aec0;margin-top:4px}
.tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid rgba(255,255,255,.06)}
.tab{padding:10px 18px;cursor:pointer;color:#718096;font-size:13px;font-weight:600;
  border-bottom:2px solid transparent;transition:all .2s}
.tab:hover{color:#e2e8f0}.tab.on{color:#63b3ed;border-bottom-color:#63b3ed}
.tc{display:none}.tc.on{display:block}
.tw{overflow-x:auto;border-radius:8px;border:1px solid rgba(255,255,255,.06)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#141c2b;color:#a0aec0;font-weight:600;text-align:left;padding:10px 12px;
  position:sticky;top:0;white-space:nowrap;border-bottom:1px solid rgba(255,255,255,.06)}
td{padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.04);white-space:nowrap}
tr:hover td{background:rgba(99,179,237,.04)}
.p{color:#48bb78}.n{color:#fc8181}
.bg{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600}
.bg-a{background:rgba(237,137,54,.15);color:#ed8936}
.bg-b{background:rgba(99,179,237,.15);color:#63b3ed}
.sb-w{display:flex;align-items:center;gap:5px}
.sb-w .br{height:5px;border-radius:3px;background:#2d3748;flex:1;max-width:70px;overflow:hidden}
.sb-w .fl{height:100%;border-radius:3px;background:linear-gradient(90deg,#63b3ed,#b794f4)}
.sb-w .nm{font-weight:700;min-width:24px;text-align:right;font-size:12px}
.rk{font-size:10px;color:#fc8181;max-width:280px;white-space:normal;line-height:1.3}
.rs{font-size:10px;color:#a0aec0;max-width:320px;white-space:normal;line-height:1.3}
.cht{background:#141c2b;border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:16px;margin-bottom:20px}
.cht-t{font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:14px}
.bc{display:flex;align-items:flex-end;gap:5px;height:140px}
.bc-c{display:flex;flex-direction:column;align-items:center;flex:1;min-width:30px}
.bc-c .bf{width:100%;max-width:28px;border-radius:3px 3px 0 0;
  background:linear-gradient(180deg,#63b3ed,#4299e1);min-height:2px;transition:height .4s}
.bc-c .bf.nb{background:linear-gradient(180deg,#fc8181,#e53e3e)}
.bc-c .bl{font-size:9px;color:#718096;margin-top:5px;writing-mode:vertical-lr;max-height:50px;overflow:hidden}
.bc-c .bv{font-size:9px;color:#a0aec0;margin-bottom:3px}
</style></head><body>
<div class="hdr"><div style="display:flex;align-items:baseline">
  <h1>📊 量化选股仪表盘</h1><span style="font-size:11px;color:#718096;margin-left:8px">v7</span>
</div><span class="ts" id="ts">加载中...</span></div>
<div class="wrap">
  <div class="cards" id="cards"></div>
  <div class="cht"><div class="cht-t">📈 TOP20 综合评分分布</div><div class="bc" id="chart"></div></div>
  <div class="tabs">
    <div class="tab on" onclick="sw('r')">推荐日志</div>
    <div class="tab" onclick="sw('d')">评分明细 TOP30</div>
  </div>
  <div class="tc on" id="t-r"><div class="tw"><table id="rt"><thead><tr></tr></thead><tbody></tbody></table></div></div>
  <div class="tc" id="t-d"><div class="tw"><table id="dt"><thead><tr></tr></thead><tbody></tbody></table></div></div>
</div>
<script>
function sw(id){
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('on',['r','d'][i]===id));
  document.querySelectorAll('.tc').forEach((c,i)=>c.classList.toggle('on',['r','d'][i]===id));
}
function cc(v){return v>0?'p':v<0?'n':''}
function sb(v,mx){
  const p=Math.max(0,Math.min(100,(v/mx)*100));
  return `<div class="sb-w"><span class="nm">${v}</span><div class="br"><div class="fl" style="width:${p}%"></div></div></div>`;
}
function render(D){
  document.getElementById('ts').textContent='更新: '+new Date().toLocaleString('zh-CN');
  const R=D.recommendations||[],S=D.scores||[];
  const A=R.filter(r=>r['类型']==='A-回调反弹'),B=R.filter(r=>r['类型']==='B-趋势延续');
  const mx=S.length?Math.max(...S.map(s=>s['综合评分'])):0;
  const ds=[...new Set(R.map(r=>r['推荐日期']))];
  document.getElementById('cards').innerHTML=`
    <div class="card"><div class="lb">推荐总数</div><div class="vl">${R.length}</div><div class="sb">${ds.length} 个交易日</div></div>
    <div class="card"><div class="lb">A类 回调反弹</div><div class="vl">${A.length}</div><div class="sb">均分 ${A.length?(A.reduce((s,r)=>s+r['综合评分'],0)/A.length).toFixed(1):'—'}</div></div>
    <div class="card"><div class="lb">B类 趋势延续</div><div class="vl">${B.length}</div><div class="sb">均分 ${B.length?(B.reduce((s,r)=>s+r['综合评分'],0)/B.length).toFixed(1):'—'}</div></div>
    <div class="card"><div class="lb">最高评分</div><div class="vl">${mx}</div><div class="sb">${S.length?S[0]['名称']:''}</div></div>`;
  // 柱状图
  const t20=S.slice(0,20);const cM=t20.length?Math.max(...t20.map(s=>Math.abs(s['综合评分']))):1;
  document.getElementById('chart').innerHTML=t20.map(s=>{
    const v=s['综合评分'],h=Math.max(3,(Math.abs(v)/cM)*120);
    return `<div class="bc-c"><div class="bv">${v}</div><div class="bf${v<0?' nb':''}" style="height:${h}px"></div><div class="bl">${s['名称']}</div></div>`;
  }).join('');
  // 推荐表
  if(R.length){
    const h=['推荐日期','代码','名称','板块','类型','综合评分','当日涨跌幅'];
    document.querySelector('#rt thead tr').innerHTML=h.map(c=>`<th>${c}</th>`).join('');
    document.querySelector('#rt tbody').innerHTML=R.map(r=>{
      const c=r['当日涨跌幅']||0;const bg=r['类型']==='A-回调反弹'?'bg-a':'bg-b';
      return `<tr><td>${r['推荐日期']}</td><td>${r['代码']}</td><td><b>${r['名称']}</b></td>
        <td>${r['板块']}</td><td><span class="bg ${bg}">${r['类型']}</span></td>
        <td>${sb(r['综合评分'],20)}</td><td class="${cc(c)}">${c>0?'+':''}${c}%</td></tr>`;
    }).join('');
  }
  // 明细表
  if(S.length){
    const fc=['频率分','胜率分','回调分','动量分','排名分','趋势分','板块分','资金分','消息分','流动性分','概念分','市场环境分','日内分'];
    const h2=['代码','名称','板块','出现天数','上涨占比','10日累涨',...fc,'综合评分','理由','风险标记'];
    const ex=h2.filter(h=>S[0].hasOwnProperty(h));
    document.querySelector('#dt thead tr').innerHTML=ex.map(c=>`<th>${c}</th>`).join('');
    document.querySelector('#dt tbody').innerHTML=S.map(s=>'<tr>'+ex.map(h=>{
      let v=s[h]!=null?s[h]:'';
      if(h==='综合评分')return `<td>${sb(v,20)}</td>`;
      if(h==='风险标记')return `<td class="rk">${v}</td>`;
      if(h==='理由')return `<td class="rs">${v}</td>`;
      if(h==='名称')return `<td><b>${v}</b></td>`;
      if(fc.includes(h)){const n=parseFloat(v)||0;return `<td class="${cc(n)}">${n}</td>`;}
      return `<td>${v}</td>`;
    }).join('')+'</tr>').join('');
  }
}
fetch('/api/data').then(r=>r.json()).then(render);
</script></body></html>"""

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,f,*a):pass
    def do_GET(self):
        if self.path=='/api/data':
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers()
            self.wfile.write(json.dumps(load_data(),ensure_ascii=False,default=str).encode('utf-8'))
        else:
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
            self.wfile.write(HTML.encode('utf-8'))

if __name__=='__main__':
    PORT=8050
    srv=http.server.HTTPServer(('0.0.0.0',PORT),H)
    print(f"\n🚀 仪表盘已启动: http://localhost:{PORT}")
    print("   按 Ctrl+C 停止服务\n")
    webbrowser.open(f'http://localhost:{PORT}')
    try:srv.serve_forever()
    except KeyboardInterrupt:print("\n仪表盘已关闭。");srv.server_close()
