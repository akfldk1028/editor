import numpy as np


def vendi_score(similarity):
    kernel = np.asarray(similarity, dtype=float)
    if kernel.ndim != 2 or not len(kernel) or kernel.shape[0] != kernel.shape[1]:
        raise ValueError('nonempty square similarity matrix required')
    if not np.isfinite(kernel).all() or not np.allclose(kernel, kernel.T, atol=1e-10, rtol=0):
        raise ValueError('finite symmetric kernel required')
    if not np.allclose(np.diag(kernel), 1, atol=1e-10, rtol=0):
        raise ValueError('unit diagonal required')
    values = np.linalg.eigvalsh(kernel / len(kernel))
    if values.min() < -1e-10:
        raise ValueError('positive semidefinite kernel required')
    values = np.maximum(values, 0)
    values /= values.sum()
    values = values[values > 0]
    return float(np.exp(-np.sum(values*np.log(values))))


def score_candidates(candidates, similarity):
    n = len(candidates)
    if not n or any(c.get('valid') is not None and type(c['valid']) is not bool for c in candidates):
        raise ValueError('candidates with explicit validity required')
    kernel = np.asarray(similarity, dtype=float)
    if kernel.shape != (n,n): raise ValueError('candidate/kernel count mismatch')
    all_score = vendi_score(kernel)
    valid = [i for i,c in enumerate(candidates) if c.get('valid') is True]
    hashes = [candidates[i].get('geometry_hash') for i in valid]
    unique = len(set(hashes)) if all(isinstance(h,str) and h for h in hashes) and hashes else None
    feasible = vendi_score(kernel[np.ix_(valid,valid)]) if len(valid)>1 else None
    return {'candidate_n': n,'valid_n':len(valid),'valid_fraction':len(valid)/n,
            'unknown_validity_n':sum(c.get('valid') is None for c in candidates),
            'unique_feasible_geometries':unique,'duplicate_feasible_n':len(valid)-unique if unique is not None else None,
            'all_vendi':all_score,'all_vendi_normalized':all_score/n,
            'feasible_vendi':feasible,'feasible_vendi_normalized':feasible/len(valid) if feasible is not None else None}
