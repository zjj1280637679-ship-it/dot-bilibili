----------------------------- MODULE Lifecycle -----------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Ops, Accounts, Budget, BypassAuthorization, RetryUnknown
VARIABLES account, phase, grant, attempts, effects, durable, authorized, used
vars == <<account, phase, grant, attempts, effects, durable, authorized, used>>
Unresolved == {"prepared", "inflight", "unknown"}
Init == /\ account \in [Ops -> Accounts]
        /\ phase = [i \in Ops |-> "draft"]
        /\ grant = [i \in Ops |-> "none"]
        /\ attempts = [i \in Ops |-> 0]
        /\ effects = [i \in Ops |-> 0]
        /\ durable = [i \in Ops |-> FALSE]
        /\ authorized = [i \in Ops |-> TRUE]
        /\ used = 0
Grant(i, g) == /\ phase[i] = "draft" /\ grant[i] = "none"
               /\ grant' = [grant EXCEPT ![i] = g]
               /\ UNCHANGED <<account, phase, attempts, effects, durable, authorized, used>>
Expire(i) == /\ grant[i] = "exact"
             /\ grant' = [grant EXCEPT ![i] = "stale"]
             /\ UNCHANGED <<account, phase, attempts, effects, durable, authorized, used>>
Phase(i, p) == /\ phase' = [phase EXCEPT ![i] = p]
               /\ UNCHANGED <<account, grant, attempts, effects, durable, authorized, used>>
Prepare(i) == /\ phase[i] = "draft" /\ grant[i] = "exact" /\ used < Budget
              /\ \A j \in Ops : (j # i /\ account[j] = account[i]) => phase[j] \notin Unresolved
              /\ phase' = [phase EXCEPT ![i] = "prepared"]
              /\ durable' = [durable EXCEPT ![i] = TRUE]
              /\ used' = used + 1
              /\ UNCHANGED <<account, grant, attempts, effects, authorized>>
Send(i) == /\ phase[i] = "prepared" /\ (grant[i] = "exact" \/ BypassAuthorization)
           /\ phase' = [phase EXCEPT ![i] = "inflight"]
           /\ attempts' = [attempts EXCEPT ![i] = @ + 1]
           /\ authorized' = [authorized EXCEPT ![i] = @ /\ grant[i] = "exact"]
           /\ UNCHANGED <<account, grant, effects, durable, used>>
Effect(i) == /\ phase[i] = "inflight" /\ effects[i] < attempts[i]
             /\ effects' = [effects EXCEPT ![i] = @ + 1]
             /\ UNCHANGED <<account, phase, grant, attempts, durable, authorized, used>>
Restart == /\ \E i \in Ops : phase[i] \in {"prepared", "inflight"}
           /\ phase' = [i \in Ops |-> IF phase[i] \in {"prepared", "inflight"} THEN "unknown" ELSE phase[i]]
           /\ UNCHANGED <<account, grant, attempts, effects, durable, authorized, used>>
Retry(i) == /\ RetryUnknown /\ phase[i] = "unknown" /\ used < Budget
            /\ phase' = [phase EXCEPT ![i] = "prepared"]
            /\ used' = used + 1
            /\ UNCHANGED <<account, grant, attempts, effects, durable, authorized>>
Next == Restart \/ \E i \in Ops :
          Grant(i, "exact") \/ Grant(i, "wrong_scope") \/ Expire(i) \/ Prepare(i) \/ Send(i) \/ Effect(i) \/ Retry(i)
          \/ (phase[i] \in {"draft", "prepared"} /\ Phase(i, "cancelled"))
          \/ (phase[i] = "inflight" /\ Phase(i, "unknown"))
          \/ (phase[i] = "inflight" /\ effects[i] < attempts[i] /\ Phase(i, "rejected"))
          \/ (phase[i] = "inflight" /\ effects[i] = attempts[i] /\ Phase(i, "applied"))
TypeOK == /\ phase \in [Ops -> {"draft", "prepared", "inflight", "applied", "rejected", "unknown", "cancelled"}]
          /\ grant \in [Ops -> {"none", "exact", "wrong_scope", "stale"}]
          /\ used \in 0..Budget
Authorization == \A i \in Ops : authorized[i]
NoReplay == \A i \in Ops : attempts[i] <= 1
DurableIntent == \A i \in Ops : attempts[i] > 0 => durable[i]
Evidence == \A i \in Ops : phase[i] = "applied" => effects[i] > 0
Exclusion == \A i, j \in Ops : (i # j /\ account[i] = account[j] /\ phase[i] \in Unresolved) => phase[j] \notin Unresolved
\* Ops is exactly two in this configuration; the summation is explicit.
Reservation == attempts["o0"] + attempts["o1"] <= used
Spec == Init /\ [][Next]_vars
=============================================================================
