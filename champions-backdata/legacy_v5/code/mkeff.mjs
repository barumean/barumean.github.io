/* 종별 '실효 메가 확률' — 상대 팀도 한 경기에 메가는 1회뿐이다.
   같은 팀에 스톤 보유자가 여럿이면 그중 하나만 메가하므로, 채택률을 팀 내 스톤 보유자
   채택률 합으로 나눠 배분하고, 래더 표본에서 그 개체가 등장한 팀들에 대해 평균낸다. */
import fs from 'fs';
import * as M from './model2.mjs';
const {D,MG}=M;
const SR=JSON.parse(fs.readFileSync('stonerate.json','utf8'));
const opps=JSON.parse(fs.readFileSync('opps100.json','utf8')).filter(o=>o.length>=4&&o.length<=6);
const sr=D.map(d=>MG[d.ko]?(SR[d.ko]||0)/100:0);
const cnt=new Array(D.length).fill(0), acc=new Array(D.length).fill(0);
for(const o of opps){
  const S=o.filter(i=>sr[i]>0).reduce((a,i)=>a+sr[i],0);
  for(const i of o){ cnt[i]++; if(sr[i]>0) acc[i]+=Math.min(1, sr[i]/Math.max(S,1)); }
}
const eff=D.map((d,i)=> sr[i]>0 ? +(cnt[i]? acc[i]/cnt[i] : sr[i]*0.65).toFixed(4) : 0);
fs.writeFileSync('effmega.json',JSON.stringify(eff));
const st=D.map((d,i)=>[d.ko,d.rank,sr[i],cnt[i],eff[i]]).filter(r=>r[2]>0).sort((a,b)=>b[4]-a[4]);
console.log('메가 가능',st.length,'종 / 팀당 평균 스톤',(opps.reduce((a,o)=>a+o.filter(i=>sr[i]>0).length,0)/opps.length).toFixed(2),'장');
console.log('실효 메가 확률 상위:',st.slice(0,6).map(r=>`${r[0]} ${(r[4]*100).toFixed(0)}%`).join(', '));
console.log('보만다 채택 97.7% → 실효',(eff[0]*100).toFixed(0)+'%');
