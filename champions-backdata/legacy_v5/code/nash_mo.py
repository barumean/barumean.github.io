import json, numpy as np, itertools, sys
from scipy.optimize import linprog
POOL=sys.argv[1] if len(sys.argv)>1 else 'full'
D=json.load(open('data100.json')); idx={m['ko']:i for i,m in enumerate(D)}
Vb=np.array(json.load(open('V100.json')));   Vm=np.array(json.load(open('V100m.json')))
Vo=np.array(json.load(open('V100o.json')));  Vmm=np.array(json.load(open('V100mm.json')))
MG=json.load(open('mega.json'))
opps=[o for o in json.load(open('opps100.json')) if 4<=len(o)<=6]
mir=np.zeros(100)
for o in opps:
    for i in o: mir[i]+=1
mir/=len(opps)
ST=np.array([1 if D[i]['ko'] in MG else 0 for i in range(100)])
def strat(members):            # (triple, mega index within triple or None)
    out=[]
    for t in itertools.combinations(range(len(members)),3):
        out.append((t,None))
        for a in t:
            if ST[members[a]]: out.append((t,a))
    return out
OSc={}
def solve(M):
    m,k=M.shape;c=np.zeros(m+1);c[-1]=-1
    A=np.hstack([-M.T,np.ones((k,1))]);b=np.zeros(k)
    Ae=np.zeros((1,m+1));Ae[0,:m]=1
    r=linprog(c,A_ub=A,b_ub=b,A_eq=Ae,b_eq=[1],bounds=[(0,None)]*m+[(None,None)],method='highs')
    return r.x[:m],-r.fun
def cell(a,b,am,bm):
    return (Vmm if (am and bm) else Vm if am else Vo if bm else Vb)[a][b]
def ev(team):
    MS=strat(team); tot=0.0; use=np.zeros(6)
    for o in opps:
        key=tuple(o)
        if key not in OSc: OSc[key]=strat(o)
        OS=OSc[key]
        M=np.array([[np.mean([cell(team[a],o[b],ma==a,mb==b) for a in ta for b in tb])
                     for (tb,mb) in OS] for (ta,ma) in MS])
        x,v=solve(M); tot+=v
        for k,(ta,ma) in enumerate(MS):
            if x[k]>1e-9:
                for a in ta: use[a]+=x[k]
    n=len(opps); u=use/n; p=u/u.sum(); p=p[p>1e-12]
    return tot/n,u,float(np.exp(-(p*np.log(p)).sum()))
cands=[];seen=set()
CF={'full':'cand_full.json','obs':'cand_obs.json','50':'cand100.json'}[POOL]
NF={'full':'nash_full.json','obs':'nash_obs.json','50':'nash100.json'}[POOL]
PF={'full':'pareto_full.json','obs':'pareto_obs.json','50':'pareto100.json'}[POOL]
for c in json.load(open(CF)):
    k=tuple(sorted(c['team']))
    if k not in seen: seen.add(k);cands.append((c['team'],c['stones']))
out=[]
for n_,(t,ns) in enumerate(cands):
    tm=[idx[x] for x in t]
    v,u,R=ev(tm)
    out.append({'v':round(v,4),'stones':ns,'team':t,'use':[round(float(x),4) for x in u],'R':round(R,3),
                'EW':round(float(sum(mir[idx[x]]*w for x,w in zip(t,u))/u.sum()*3),3)})
    if n_%25==0: print(n_,flush=True)
out.sort(key=lambda r:-r['v'])
json.dump(out,open(NF,'w'),ensure_ascii=False)
def dom(a,b): return a['v']>=b['v'] and a['R']>=b['R'] and a['EW']<=b['EW'] and (a['v']>b['v'] or a['R']>b['R'] or a['EW']<b['EW'])
res={'mir':[round(float(x),4) for x in mir]}
for k in (0,1,2):
    grp=[r for r in out if r['stones']==k]
    fr=[r for r in grp if not any(dom(o,r) for o in grp)]
    fr.sort(key=lambda r:-r['v'])
    res[str(k)]={'front':fr[:8],'scat':[[r['v'],r['R']] for r in grp],
                 'flag':[1 if any(f is r for f in fr) else 0 for r in grp],
                 'best':grp[0] if grp else None,'n':len(grp),'nfront':len(fr)}
    print('스톤',k,'팀',len(grp),'최고',grp[0]['v'] if grp else None,'파레토',len(fr))
json.dump(res,open(PF,'w'),ensure_ascii=False)
for r in out[:5]: print(r['v'],'/'.join(r['team']))
