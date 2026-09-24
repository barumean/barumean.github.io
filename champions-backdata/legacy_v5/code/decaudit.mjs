import fs from 'fs';
const DEX=JSON.parse(fs.readFileSync('raw2/dex2.json','utf8'));
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const U=JSON.parse(fs.readFileSync('usage100.json','utf8'));
const rows=[];
for(const d of D){
  const r=DEX[d.ko]||{};
  const shown=Object.values(r.moves||{}).reduce((a,b)=>a+b,0);
  const sc=shown>0?Math.min(400/shown,1.6):1;
  const u=U[d.ko]||{};
  const nShown=Object.keys(r.moves||{}).length;
  const atk=(d.atkMoves||[]);
  const shownSet=new Set(Object.keys(r.moves||{}));
  const covered=atk.filter(m=>shownSet.has(m)).length, total=atk.length;
  const capped=sc>=1.599?1:0;
  const flags=[];
  if(capped) flags.push('절단보정 상한');
  if(shown<250) flags.push('노출 합 낮음');
  if(covered<total) flags.push('노출 밖 기술 '+(total-covered)+'개');
  if((r.asum??100)<95) flags.push('특성 합 '+r.asum+'%');
  if((r.isum??100)<95) flags.push('아이템 합 '+r.isum+'%');
  rows.push([d.rank,d.ko,nShown,shown.toFixed(1),sc.toFixed(3),r.asum??'',r.isum??'',
    covered,total,'',flags.join(' / ')||'-',flags.length?'주의':'']);
}
const head=['rank','ko','노출_기술수','노출_채용률합','절단보정계수','특성합','아이템합',
  '채용률있는_공격기','전체_공격기','기본값_%','경고','신뢰도'];
fs.writeFileSync((process.env.EXPORT_DIR||'/tmp/bd/')+'csv/13_decode_audit.csv','﻿'+[head.join(','),
  ...rows.map(r=>r.map(x=>{const s=String(x??'');return /[",]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}).join(','))].join('\n'));
const warn=rows.filter(r=>r[11]==='주의');
console.log('복원 감사표 생성. 경고 있는 개체',warn.length,'/',rows.length);
console.log('절단보정 상한(1.6)에 걸린 개체:',rows.filter(r=>+r[4]>=1.599).length);
console.log('예:',warn.slice(0,6).map(r=>r[1]+'['+r[10]+']').join(' · '));
