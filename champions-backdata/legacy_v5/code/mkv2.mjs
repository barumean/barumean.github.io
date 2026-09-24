import fs from 'fs';
import {CANON} from './config.mjs';
import * as M from './model2.mjs';
const {D,value,calcNbar}=M; const C=M.CAL;
const FINAL=CANON;
const N=D.length;
function build(mix){
  Object.assign(C,FINAL,{mix}); calcNbar();
  const V=[],VM=[],VO=[],VMM=[];
  const st=D.map(d=>M.MG[d.ko]?1:0);
  for(let i=0;i<N;i++){const a=[],b=[],c=[],d2=[];
    for(let j=0;j<N;j++){a.push(+value(i,j,0,0).toFixed(4));b.push(+value(i,j,1,0).toFixed(4));
      c.push(st[j]?+value(i,j,0,1).toFixed(4):0); d2.push((st[i]&&st[j])?+value(i,j,1,1).toFixed(4):0);}
    V.push(a);VM.push(b);VO.push(c);VMM.push(d2);}
  return {V,VM,VO,VMM};
}
const base=build(CANON.mix);              // 설정의 mix를 그대로 따른다
fs.writeFileSync('V100.json',JSON.stringify(base.V));
fs.writeFileSync('V100m.json',JSON.stringify(base.VM));
fs.writeFileSync('V100o.json',JSON.stringify(base.VO));    // 상대가 메가
fs.writeFileSync('V100mm.json',JSON.stringify(base.VMM));  // 둘 다 메가
const u=build(CANON.mix>=1?0:1);          // 비교용: 반대쪽 가정
fs.writeFileSync('V100u.json',JSON.stringify(u.V));
console.log('V100/V100m/V100o/V100mm/V100u 재생성 완료', N+'x'+N);
// 기술 채용 폭: 공격기술 채용률 합 / 100 = 평균 보유 공격기술 수
const USE=JSON.parse(fs.readFileSync('usage100.json','utf8'));
const COV={};
for(const d of D){ const r=USE[d.ko]?.r||{}; COV[d.ko]=+(Object.values(r).reduce((a,b)=>a+b,0)/100).toFixed(2); }
fs.writeFileSync('cov100.json',JSON.stringify(COV));
const s=Object.entries(COV).sort((a,b)=>a[1]-b[1]);
console.log('공격기술 보유 수 최소:',s.slice(0,6).map(x=>x[0]+' '+x[1]).join(', '));
console.log('              최대:',s.slice(-6).map(x=>x[0]+' '+x[1]).join(', '));
