import {useEffect,useMemo,useState} from 'react';
import {getClaims} from '../services/claimService';
import ClaimTable from '../components/ClaimTable';

export default function Claims(){
 const [claims,setClaims]=useState([]),[query,setQuery]=useState(''),[status,setStatus]=useState('all'),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 useEffect(()=>{getClaims().then(r=>setClaims(r.data)).catch(e=>setError(e.response?.data?.detail||'Could not load claims. Check the API connection.')).finally(()=>setLoading(false))},[]);
 const filtered=useMemo(()=>claims.filter(c=>(status==='all'||c.status===status)&&(`${c.claim_id} ${c.hospital} ${c.diagnosis} ${c.provider_id||''}`).toLowerCase().includes(query.toLowerCase())),[claims,status,query]);
 return <><div className="title"><span className="eyebrow">REGISTRY</span><h1>Claims management</h1><p>Search claims, review separate risk signals, and open claim details.</p></div><section className="panel"><div className="filters"><label>Search claims<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Claim ID, provider, hospital, diagnosis"/></label><label>Status<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">All statuses</option><option value="pending">Pending</option><option value="under_investigation">Under investigation</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label><span>{filtered.length} claim{filtered.length===1?'':'s'}</span></div>{loading?<div className="loading">Loading claims…</div>:error?<div className="error" role="alert">{error}</div>:<ClaimTable claims={filtered}/>}</section></>
}
