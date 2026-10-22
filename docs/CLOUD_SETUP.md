# Setting up Google sign-in and cloud storage

This guide turns on two things:

- **Google sign-in**, through Streamlit's built-in login.
- **Saved pies in Supabase**, so they follow the user across devices.

Without these steps the app still works: pies are saved in `saved_pies.json` on the machine running it.

Allow about 30 minutes. You need:

- a Google account
- a free [Supabase](https://supabase.com) account
- this repo, with `pip install -r requirements.txt` done

## How it fits together

- Users sign in with Google. The app knows them as `google:<their Google id>`.
- Only the Streamlit server talks to Supabase. It uses a secret server key, and every query is limited to the signed-in user's own pies, plus pies marked public.
- The database has row-level security switched on with no rules. The public "anon" key therefore can't read or write anything, even if it leaks.

## Step 1: Create the Google login client

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project, for example "Pie backtester". Use the project picker at the top.
2. Go to **APIs & Services → OAuth consent screen**. In newer consoles this is called **Google Auth Platform**. Click **Get started**.
   - **App name:** Pie backtester. **Support email:** your email.
   - **Audience:** External.
   - **Contact email:** your email. Accept the terms, then **Create**.
3. Under **Audience → Test users**, add your own Google address. While the app is in *Testing* mode, only test users can sign in.
4. Go to **Clients** (or **Credentials → Create credentials → OAuth client ID**):
   - **Application type:** Web application
   - **Name:** Pie backtester (local)
   - **Authorized redirect URIs:** `http://localhost:8501/oauth2callback`
5. Click **Create**, then copy the **Client ID** and **Client secret**. You'll need them in step 4.

You don't need to add scopes. Sign-in only uses the basic `openid`, `email` and `profile` information.

## Step 2: Create the Supabase database

1. In [Supabase](https://supabase.com/dashboard), click **New project**.
   - Pick a name, a database password (save it somewhere) and a region close to your users.
   - Wait for the project to finish setting up.
2. Open **SQL Editor → New query**. Paste the whole of [`schema.sql`](../schema.sql) and click **Run**. You should see "Success. No rows returned".
   - This creates the `pies` table and switches on row-level security.
   - If you ran an older `schema.sql` before, the same script upgrades that table.
3. Check the result in **Table Editor**. There should be a `pies` table with a `owner_id` column of type `text`, and it should be marked *RLS enabled*.

## Step 3: Copy the Supabase URL and secret key

In **Project Settings → API Keys**, which also shows your project URL at the top or under **Data API**:

- **Project URL**, like `https://abcd1234.supabase.co`.
- **A secret key.** Either one works:
  - the new **Secret key** (`sb_secret_...`): click **Create new secret key** if there isn't one yet
  - the legacy **service_role** key: a long `eyJ...` string under *Legacy API keys*

> **Don't use the "anon" or "publishable" key.** It can't do anything here, by design. Keep the secret key private: put it only in `secrets.toml` or your hosting platform's secrets. Never commit it, and never paste it into a browser page.

## Step 4: Write the secrets file

1. Create a long random cookie secret:

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Create `.streamlit/secrets.toml` in the repo folder. It's gitignored, so it won't be committed. Fill in your values:

   ```toml
   SUPABASE_URL = "https://abcd1234.supabase.co"
   SUPABASE_SERVICE_KEY = "sb_secret_..."            # or the legacy service_role key

   [auth]
   redirect_uri = "http://localhost:8501/oauth2callback"
   cookie_secret = "paste-the-random-string-from-step-1"

   [auth.google]
   client_id = "1234567890-abc.apps.googleusercontent.com"
   client_secret = "GOCSPX-..."
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

3. Check that git ignores it. This should print the file name:

   ```bash
   git check-ignore .streamlit/secrets.toml
   ```

If you used an earlier version of this app, delete the old `SUPABASE_KEY` line. That was the anon key, and the app now ignores it with a warning.

## Step 5: Try it locally

```bash
streamlit run app.py
```

Open <http://localhost:8501> and work through this checklist:

- [ ] **Signed out:** the sidebar shows **Sign in with Google**, and there's no "Use guest account" button.
- [ ] **Load an example pie:** under *My saved pies* it says "Sign in to save pies".
- [ ] **Sign in** with your test user. The sidebar shows your name and "Log out".
- [ ] **Save a pie:** you see "Saved pie '…'", and the pie appears in the saved-pies list.
- [ ] **In Supabase → Table Editor → pies:** the new row has `owner_id` = `google:…`.
- [ ] **Save a second pie with "Make public" ticked.**
- [ ] **Open a private browser window, not signed in:** you see only the public pie. You can load it, but there's no Delete button.
- [ ] **Back in your signed-in window, delete a pie:** you see "Deleted pie '…'", and the row is gone in Supabase.
- [ ] **Log out and back in:** your pies are still there.

If something doesn't match, see [Troubleshooting](#troubleshooting).

## Step 6: Deploy

These steps are for [Streamlit Community Cloud](https://share.streamlit.io). Other hosts work the same way: secrets go in the host's secret settings, and the redirect URI uses the public URL.

1. Push the code to GitHub. The secrets file stays on your machine.
2. In Streamlit Community Cloud, click **Create app** and pick the repo, branch and `app.py`.
3. In **Advanced settings → Secrets**, paste the contents of your `secrets.toml`. Change one line:

   ```toml
   redirect_uri = "https://your-app-name.streamlit.app/oauth2callback"
   ```

4. In the Google Cloud Console, open your OAuth client and add the same URI under **Authorized redirect URIs**. Keep the localhost URI if you still develop locally.
5. Deploy, then run the step 5 checklist again on the live URL.
6. When other people should be able to sign in, go to **Audience** in the Google console and click **Publish app**. Until then, only the test users you added can log in. With only the basic profile information, Google usually doesn't require a review.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| "Google sign-in isn't set up, so pies can't be saved" | The `[auth]` or `[auth.google]` section is missing a key. All of `redirect_uri`, `cookie_secret`, `client_id`, `client_secret` and `server_metadata_url` are needed. Restart Streamlit after editing secrets. |
| A yellow warning about `SUPABASE_KEY` | You still have the old anon key setting. Replace it with `SUPABASE_SERVICE_KEY` (step 3). |
| Google says `redirect_uri_mismatch` | The URI in `secrets.toml` and the one in the Google client must match exactly: `http` vs `https`, port, and no trailing slash. |
| Google says "Access blocked" or that the app hasn't completed verification | Your account isn't a test user (step 1.3), or publish the app (step 6.6). |
| "Failed to save pie: HTTP 401" or "permission denied" | The key isn't the secret/service_role key. Copy it again (step 3). |
| "Failed to save pie: HTTP 404" or "relation pies does not exist" | `schema.sql` hasn't been run in this project (step 2.2). |
| "Maximum pie limit (20) reached" | Each user can keep 20 pies. Delete one, or raise `MAX_PIES_PER_USER` in `storage.py`. |
| Saved pies disappear after a restart in local mode | Without Supabase, pies live in `saved_pies.json` in the folder the app runs from. |

## Good to know

- **The secret key bypasses row-level security.** Only the app's own code keeps users' pies apart: every query is filtered by `owner_id` in `storage.py`, and `tests/test_supabase.py` covers it. Keep that in mind if you add new database queries.
- **Public pies** are visible to everyone, including visitors who aren't signed in, but only their owner can delete them.
- **To rotate the secret key,** create a new one in Supabase, update the secrets (locally and on the host), then delete the old key.
