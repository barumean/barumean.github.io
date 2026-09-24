/* 기술 추천기 블록 생성 — 100종 각각의 추천 4기와 근거를 미리 계산해 페이지에 넣는다. */
import fs from 'fs';
import * as S from './setopt.mjs';
import * as M from './model2.mjs';
const {D,mvT,mvC}=M;
const W=JSON.parse(fs.readFileSync('oppw100.json','utf8'));
const tw=W.reduce((a,b)=>a+b,0);
const out={}; const t0=Date.now();
const catOf=m=>mvC(m)==='물리'?'물':mvC(m)==='특수'?'특':'변';
for(let i=0;i<D.length;i++){
  const ko=D[i].ko; if(ko==="메타몽"){ out[ko]={skip:"상대를 복사하는 개체라 고유 기술 세트가 없습니다."}; continue; }
  const ctx=S.prep(i);
  const best=(k,reserve=[])=>{
    // reserve: 모델이 값을 못 매기지만 실전 4기에 든 변화기 — 칸만 차지하고 점수엔 0
    const save=ctx.fixed; const pp=m=>ctx.pool.find(x=>x.mv===m)?.p??0;
    ctx.fixed=[...new Set([...reserve,...save])].sort((a,b)=>pp(b)-pp(a)).slice(0,k);
    const r=S.bestSets(ctx,k); ctx.fixed=save; return r;
  };
  const real=ctx.pool.slice(0,4).map(x=>x.mv);
  /* 실전 4기 중 그대로 둘 칸: 값을 못 매기는 기술 + 회복기.
     회복기는 교체가 오가는 긴 경기에서 값이 나오는데 1:1 턴 경쟁 모델은 이를 과소평가한다
     (특히 위협이 약한 내구형은 내구 값이 0으로 잘린다). 그래서 모델이 회복기를 빼자고 하면 믿지 않는다. */
  const reserve=real.filter(m=>S.unvalued(m)||S.role(m)==="회복");
  const realS=Math.max(S.score(ctx,real,"물리"),S.score(ctx,real,"특수"));
  const realInv=S.score(ctx,real,"물리")>=S.score(ctx,real,"특수")?"물리":"특수";
  const A=(()=>{ const sv=ctx.fixed; ctx.fixed=[]; const r=S.bestSets(ctx,4); ctx.fixed=sv; return r; })();   // 참고: 고정·예약 없이 모델만으로
  const B=best(4,reserve);            // 실전 70%+ 기술과 값을 못 매기는 실전 4기 칸은 그대로 두고 나머지만 최적
  const rec=B.length?B[0]:A[0];
  if(!rec){ out[ko]={skip:"채용률 10% 이상 공격기가 없습니다."}; continue; }
  const det=S.score(ctx,rec.set,rec.inv,true);
  // 기술별: 빼고 다른 후보로 바꿨을 때 가장 좋은 점수와의 차이
  const pool=ctx.cand.map(x=>x.mv);
  const moves=rec.set.map(m=>{
    const p=ctx.pool.find(x=>x.mv===m)?.p??0, r=S.role(m);
    let drop=null;
    if(!S.unvalued(m) && !ctx.fixed.includes(m) && !reserve.includes(m)){
      let alt=-9, altMv=null;
      const others=rec.set.filter(x=>x!==m);
      for(const x of [...pool.filter(x=>!rec.set.includes(x)), null]){
        const s2=S.score(ctx, x?[...others,x]:others, rec.inv); if(s2>alt){alt=s2;altMv=x;}
      }
      drop={d:+(rec.s-alt).toFixed(4), alt:altMv};
    }
    const bw=det.per.filter(q=>q.mv===m).reduce((a,q)=>a+W[q.j],0);
    return {mv:m,ty:mvT(m),c:catOf(m),p,r,fix:p>=S.OPT.anchor&&!reserve.includes(m),res:reserve.includes(m),drop,best:+(bw/tw*100).toFixed(1)};
  });
  const holes=det.per.filter(q=>q.v<=-0.33).sort((a,b)=>W[b.j]-W[a.j]).slice(0,6).map(q=>[D[q.j].ko,+(W[q.j]/tw*100).toFixed(1),+q.v.toFixed(2)]);
  const wins=det.per.filter(q=>q.v>=0.33).reduce((a,q)=>a+W[q.j],0)/tw*100;
  const loss=det.per.filter(q=>q.v<=-0.33).reduce((a,q)=>a+W[q.j],0)/tw*100;
  out[ko]={mega:ctx.mi, inv:rec.inv, s:+rec.s.toFixed(4), moves, holes, win:+wins.toFixed(1), lose:+loss.toFixed(1),
    real:real.map(m=>({mv:m,c:catOf(m),r:S.role(m),p:ctx.pool.find(x=>x.mv===m).p})), realS:+realS.toFixed(4), realInv,
    modelOnly: A[0] ? {set:A[0].set, s:+A[0].s.toFixed(4), inv:A[0].inv} : null,
    alt: (B[1]&&B[1].set.join()!==rec.set.join()) ? {set:B[1].set, s:+B[1].s.toFixed(4)} : null,
    free: Math.max(0,4-new Set([...reserve,...ctx.cand.filter(x=>x.p>=S.OPT.anchor).map(x=>x.mv)]).size),
    excluded: ctx.pool.filter(x=>(x.atk||x.su||x.rec)&&x.p<S.OPT.floor).map(x=>[x.mv,x.p]),
    outside: ctx.pool.filter(x=>S.unvalued(x.mv)).map(x=>[x.mv,x.p,S.role(x.mv)]),
    reserved: reserve};
}
fs.writeFileSync('sets_blocks.json',JSON.stringify(out));
const same=Object.values(out).filter(o=>o.moves&&o.real&&o.moves.map(m=>m.mv).sort().join()===o.real.map(m=>m.mv).sort().join()).length;
console.log(`생성 ${Object.keys(out).length}종 · ${((Date.now()-t0)/1000).toFixed(1)}초 · ${fs.statSync('sets_blocks.json').size}B`);
console.log(`추천 = 실전 최다 4기와 동일: ${same}종`);
const gain=Object.entries(out).filter(([,o])=>o.s!==undefined).map(([k,o])=>[k,o.s-o.realS]).sort((a,b)=>b[1]-a[1]);
console.log('개선 폭 상위:',gain.slice(0,8).map(x=>x[0]+' +'+x[1].toFixed(3)).join(', '));
