# Safe AI

What Ask Zetty, and AI clients connected over MCP, can and cannot do on your NAS. Each point
names the test or the page that holds it, so you can check it yourself.

## It runs here

- **Search runs on the NAS.** Files are indexed and searched on this server; the index
  (`rag_index.db`) and your conversations stay on it, encrypted with the install's data key.
  Search works without any AI model (see [Search quality](SEARCH_QUALITY.md)).
- **Answers come from a model on the NAS** (Ollama or OpenVINO Model Server), unless you set
  another address in **AI settings**. ZettNAS never looks for AI servers on your network.
- **No account, no subscription.** Nothing needs signing up, and no feature is behind a plan.
- **Web search is off** in every chat until you turn on **Web** for it. A web search carries
  the question without addresses, e-mail addresses, file paths, long numbers or keys, and a
  search that repeats text from your files is refused. Everything that can leave the NAS is
  listed in [PRIVACY.md](PRIVACY.md); `tests/test_sec38_privacy.py` fails when the code
  contacts a host that page doesn't name.

## It sees only what you may see

- **Results and answers include only files from shares the signed-in person can open.** A
  search that doesn't say who is asking finds nothing (`tests/test_sec37_fail_closed.py`).
- **The chat gets only the tools the person's role allows**, the same permissions as the
  matching pages. An AI client over MCP gets the permissions of its API token's account,
  and a token limited to folders reaches nothing outside them, even an administrator's
  (`tests/test_comp06_token_safety.py`). Security → API Tokens shows which client used each
  token last, and **Revoke** cuts it off.
- **Text from files and web pages is data, not instructions.** It is passed to the model
  marked as such, and the model is told not to follow instructions inside it.

## It doesn't act on its own

- **Anything that changes the system waits for you.** Changing a fan profile, starting or
  stopping an app or indexing a folder shows what will happen and runs only after you click
  **Confirm**. For an MCP client, that is a link you open in ZettNAS; it expires after 10
  minutes and works only for the same account.
- **Every tool call is in the security audit log** (`ai.tool.call`, `ai.tool.confirmed`).
- **Risky Compose files are flagged.** When an answer contains a Compose file with privileged
  mode, the Docker socket, host networking, system folders, raw disks or default passwords,
  it ends with a note listing them.

## It shows its sources

- **Answers cite the files they used**, and the chat says how many sentences the sources
  back up and lists the ones they don't ([how answers are checked](RAG.md#how-answers-are-checked)).
- **If no model answered, it says so** instead of passing off search results as an answer,
  and if the chosen model isn't installed it says that instead of using another one.
- **Quality is measured in the open.** The scores on [Search quality](SEARCH_QUALITY.md) come
  from a public test set, with a fifth of the questions held out from all tuning.

## You can make it forget

- **Forget** on a watched folder deletes everything learned from it and stops it being read
  again; **Excluded** folders are never read.
- **Delete chats not used for…** removes old conversations after 7, 30, 90 or 365 days, and
  **Flush index** deletes the whole index.

Found something that doesn't hold? Please report it as described in [SECURITY.md](../SECURITY.md).
