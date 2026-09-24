/* 래더 표본 관측 횟수 대 모델 후보 등장 횟수 — 외삽 경고표 */
import fs from 'fs';
const O=process.env.EXPORT_DIR||'/tmp/bd/';
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const OP=JSON.parse(fs.readFileSync('opps100.json','utf8'));
const NS=JSON.parse(fs.readFileSync('nash_full.json','utf8'));
const cnt=new Array(D.length).fill(0);
for(const t of OP) for(const x of t) cnt[x]++;
const inc={}; for(const r of NS) for(const k of r.team) inc[k]=(inc[k]||0)+1;
const rows=D.map((d,i)=>[d.rank,d.ko,cnt[i],+(cnt[i]/OP.length*100).toFixed(1),
  inc[d.ko]||0, +((inc[d.ko]||0)/NS.length*100).toFixed(1),
  (cnt[i]<=3&&(inc[d.ko]||0)>=30)?'외삽 경고':(cnt[i]<=3?'저표본':'')]);
rows.sort((a,b)=>(b[4]-a[4])||(a[2]-b[2]));
const head=['rank','ko','ladder_count_'+OP.length,'ladder_pct','in_candidate_teams_'+NS.length,'candidate_pct','flag'];
fs.writeFileSync(O+'csv/14_sample_vs_model.csv','﻿'+[head.join(','),
  ...rows.map(r=>r.map(x=>{const s=String(x??'');return /[",]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}).join(','))].join('\n'));
const w=rows.filter(r=>r[6]==='외삽 경고');
console.log('표본 대조표 생성. 외삽 경고',w.length,'종:',w.map(r=>r[1]+'('+r[2]+'회/'+r[4]+'팀)').join(' '));
