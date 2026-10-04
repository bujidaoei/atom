# Deployment — responsive preview and generation repair

## Candidate identity
- Source: f27a9b2b3cd7ade3a37f77a4180d41ab4016a93a, pushed to codex/012-responsive-preview and main.
- Clean root-owned checkout: /home/ubuntu/atom-responsive-preview.
- Image: sha256:142ba90e6a78f9f518d8fe5db3a5078d4d96be8d9825171554d1db5116011d39; /atom/ frontend base.
- Prior live source: a621b9b968c326e87db5faef1ed962ff35627ec0; prior image sha256:58f9eeed2cf60664e69a3366d667656e064c1172363f0d0659a80bf9e17ed9b0.

## Preflight
Existing SSH key/Git authorization used; no supplied passwords were persisted. Current-generation verification and successor preflight passed with82 active origins, exact six-container identities, schema18/3, unchanged topology and generation budgets3600s. Public port20073 returned certificate-verified HTTP200 and HTML SHA2564a3b8558d8863990a5fc323f1bbf30895d9f36430c49a738451a9afca582a980. No running project/run was observed before release preparation.

The current protected forward transaction was dispatched as atom-deploy-responsive-preview. It owns maintenance, quiescence, paired temporary backup, candidate start and exposure. The temporary backup will be retained through acceptance and then removed to honor the prior no-retained-backup preference. Active candidate data must never be deleted as backup cleanup.

## First candidate acceptance boundary
The first candidate required CR-002 before final acceptance. The accepted-phase journal must only be advanced after actual checks. Before durable successor writes, use the existing guarded forward recovery; after writes, preserve successor data and use forward correction, never restore stale project data.


## Final accepted release
- Source: d003710535cb660ef61a2edc2085f2de2ef7de39, synchronized to feature and main before deployment; later documentation-only commits retain identical implementation.
- Root-owned clean checkout: /home/ubuntu/atom-responsive-final.
- Exact image: sha256:542cbda152b4ccd664d3de5a8b895c65a881dfad2df41c5c8e794f1a126f9c59, matching source and /atom/ labels; 68 Linux tests passed.
- Protected transaction: atom-deploy-responsive-final, successful exit ; final journal /var/lib/atom-cutovers/d003710535cb660ef61a2edc2085f2de2ef7de39.forward-phase.json is `accepted`. Prior f27a9b2 journal is `successor_retained` because repaired user data was preserved and carried forward.
- Active data: /var/backups/atom-cutovers/forward-candidate-d003710535cb. This is live data. Never remove it as backup cleanup.
- API/broker/preview/public/verifier/TLS healthy; current-generation preflight returned `current_generation_verified`, 82 origins and ingress SHA256 c803e66aa8f87f61f35b05e61d83efc636e501c9ee83b54ce1977ec8f834585e.
- Public port 20073 is certificate-verified HTTP200 with the unchanged pre-release content hash above.
- Real repair Run 7ab638b221844732b671d4593da505cf completed and saved fd9ac7b7afe34e928efda0a43ce0aae7 ; final live three-mode, exact popup version, console isolation and chess interactions passed (details in evidence.md).

After acceptance, exact-path/no-symlink/root-owner checks removed only the two newly created temporary directories forward-pre-f27a9b2b3cd7 (189824968 bytes) and forward-pre-d003710535cb (189960906 bytes). Active data was checked intact. These temporary rollback backups are no longer available; preserve current data and use forward correction after durable writes. Other prior source/candidate directories were not removed. Existing 3600s generation policy is retained, with the new bounded repair default 2.
