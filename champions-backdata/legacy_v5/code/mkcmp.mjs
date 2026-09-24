import fs from 'fs';
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const V=JSON.parse(fs.readFileSync('V100.json','utf8'));
const U=JSON.parse(fs.readFileSync('V100u.json','utf8'));
const COV=JSON.parse(fs.readFileSync('cov100.json','utf8'));
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const wsum=W.reduce((a,b)=>a+b,0);
const rows=D.map((m,i)=>{
  let a=0,b=0;
  for(let j=0;j<100;j++){ if(i===j)continue; a+=W[j]*V[i][j]; b+=W[j]*U[i][j]; }
  return {ko:m.ko, rank:m.rank, a:a/wsum, b:b/wsum, cov:COV[m.ko]};
});
const ord=x=>[...rows].sort((p,q)=>q[x]-p[x]).map(r=>r.ko);
const oa=ord('a'), ob=ord('b');
rows.forEach(r=>{ r.ra=oa.indexOf(r.ko)+1; r.rb=ob.indexOf(r.ko)+1; r.d=r.rb-r.ra; });
const out=rows.map(r=>[r.ko,r.rank,+r.a.toFixed(3),+r.b.toFixed(3),r.ra,r.rb,r.cov]);
fs.writeFileSync('blk_cov.js','const COVCMP='+JSON.stringify(out)+';\n');
console.log('■ 채용률 반영 시 가장 많이 내려가는 10 (커버리지 과대평가)');
[...rows].sort((x,y)=>y.d-x.d).slice(0,10).forEach(r=>console.log(`  ${r.ko.padEnd(11)} 실제${String(r.rank).padStart(3)}위 | 모델 ${r.ra}→${r.rb}위  공격기술 ${r.cov}개`));
console.log('■ 가장 많이 올라가는 10 (기술이 실제로 모이는 쪽)');
[...rows].sort((x,y)=>x.d-y.d).slice(0,10).forEach(r=>console.log(`  ${r.ko.padEnd(11)} 실제${String(r.rank).padStart(3)}위 | 모델 ${r.ra}→${r.rb}위  공격기술 ${r.cov}개`));
