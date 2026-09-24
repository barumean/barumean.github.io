import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,ttk,calcNbar,NBAR}=M; const C=M.CAL;
Object.assign(M.CAL, CANON); calcNbar();
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const wsum=W.reduce((a,b)=>a+b,0);
const DEC={};
D.forEach((m,i)=>{
  let o=0,d=0;
  for(let j=0;j<100;j++){ if(i===j)continue;
    const ni=ttk(i,j,0,0), nj=ttk(j,i,0,0);
    const si=D[i].s[5], sj=D[j].s[5];
    const fast=si>sj?C.spd:si<sj?-C.spd:0;
    const ov=Math.max(-1,Math.min(1,((nj-ni)+fast)/C.K));
    let dv=Math.max(-1,Math.min(1,(nj-NBAR.v)/NBAR.v));
    if(dv>0) dv*=Math.max(0,Math.min(1,1-(ni-NBAR.v)/NBAR.v));
    o+=W[j]*ov; d+=W[j]*dv;
  }
  o/=wsum; d/=wsum;
  const tot=(1-C.beta)*o+C.beta*d;
  // 내구 의존도: 종합 점수 중 내구항이 차지하는 비중 (양수일 때만 의미)
  const share = tot>0 ? Math.max(0,Math.min(1, (C.beta*d)/tot)) : 0;
  DEC[m.ko]=[+o.toFixed(3),+d.toFixed(3),+tot.toFixed(3),+share.toFixed(2),+m.rec.toFixed(2)];
});
fs.writeFileSync('blk_dec.js','const DEC='+JSON.stringify(DEC)+';\n');
const e=Object.entries(DEC).filter(x=>x[1][2]>0).sort((a,b)=>b[1][3]-a[1][3]);
console.log('■ 내구 의존도 높은 상위 10 (종합점수가 양수인 개체 중)');
e.slice(0,10).forEach(([k,v],n)=>{const r=D.find(x=>x.ko===k).rank;
  console.log(`  ${k.padEnd(11)} 티어${String(r).padStart(3)}위  공격 ${v[0]>=0?'+':''}${v[0]}  내구 +${v[1]}  종합 +${v[2]}  내구비중 ${(v[3]*100).toFixed(0)}%  회복 ${v[4]}`);});
