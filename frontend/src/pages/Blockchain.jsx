import {useEffect,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {getClaims} from '../services/claimService';

const label=s=>s==='unavailable_not_configured'?'Not configured':s||'Pending';
export default function Blockchain(){
 const [claims,setClaims]=useState([]),[error,setError]=useState(''),[loading,setLoading]=useState(true),[searchParams]=useSearchParams();
 const focusClaim=searchParams.get('claim_id');
 const displayedClaims=focusClaim?claims.filter(c=>c.claim_id===focusClaim):claims;
 useEffect(()=>{getClaims().then(r=>setClaims(r.data)).catch(e=>setError(e.response?.data?.detail||'Could not load blockchain records from the API.')).finally(()=>setLoading(false))},[]);
 return <><div className="title"><div><span className="eyebrow">AUDIT TRAIL</span><h1>Blockchain records</h1><p>Transaction data shown only when returned by the backend. A local decision hash is not an on-chain confirmation.</p></div>{focusClaim&&<Link className="button-link" to={`/claims/${focusClaim}`}>Back to claim</Link>}</div>{focusClaim&&<p className="notice">Showing blockchain record for claim {focusClaim}.</p>}<section className="panel">{loading?<div className="loading">Loading blockchain records...</div>:error?<div className="error" role="alert">{error}</div>:<div className="tablewrap"><table><thead><tr><th>Claim</th><th>Decision status</th><th>Transaction hash</th><th>Block</th><th>Claim status</th><th>Record match</th></tr></thead><tbody>{displayedClaims.map(c=><tr key={c.claim_id}><td><Link to={`/claims/${c.claim_id}`}>{c.claim_id}</Link></td><td>{label(c.blockchain?.verification_status)}</td><td className="hash">{c.blockchain?.transaction_hash||'No transaction recorded'}</td><td>{c.blockchain?.block_number??'Not available'}</td><td><span className="status">{(c.status||'pending').replaceAll('_',' ')}</span></td><td>{c.blockchain?.record_matches===true?'Yes':c.blockchain?.record_matches===false?'No':'Not checked'}</td></tr>)}{!displayedClaims.length&&<tr><td colSpan="6" className="empty">{focusClaim?'No blockchain record was returned for this claim.':'No claim records returned by the API.'}</td></tr>}</tbody></table></div>}</section></>
}
