# Getting Started with Security Policy Generation System

A beginner-friendly guide to set up and use the system.

## 5-Minute Quick Start

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-org/SecPolicy_Gen.git
cd SecPolicy_Gen
```

### Step 2: Set Up Environment

Create `infrastructure/.env`:

```env
OPENAI_API_KEY=sk-your-api-key-here
FLASK_SECRET_KEY=change-this-in-production
FLASK_ENV=development
MONGO_URI=mongodb://mongo:27017/policy-gen-db
CHROMA_HOST=chroma
CHROMA_PORT=8000
POLICY_AGENT_URL=http://policy-agent:5000
```

> **Get your OpenAI API key:** https://platform.openai.com/account/api-keys

### Step 3: Start Everything

```bash
make up
```

Wait for all services to be ready (usually 30-60 seconds).

### Step 4: Access the System

- **Web Interface:** http://localhost:3000
- **Start creating policies!**

### Step 5: Stop Everything

```bash
make down
```

---

## System Overview

The system works in three stages:

### 1. **Context Collection** (Context Agent)
- User answers questions about their organization
- Captures: country, sector, size, compliance needs
- Generates a structured context document

### 2. **Policy Generation** (Policy Agent)
- Receives the context from step 1
- Searches regulatory database for relevant standards
- Generates a comprehensive security policy
- Creates multiple versions if needed

### 3. **Validation** (Validator Agent)
- Reviews the generated policy
- Checks compliance, logic, and tone
- Requests revisions up to 3 times if needed
- Approves the final policy

---

## Understanding the Flow

```
You Fill Out Form
    ↓
Context Agent Processes Answers
    ↓
Policy Agent Generates Policy
    ↓
Validator Agent Reviews
    ↓
Need Changes? ──→ [Repeat steps 3-4]
    ↓ No
Final Policy Approved ✓
```

---

## Using the System

### First Time Usage

1. **Open** http://localhost:3000
2. **Click** "New Context" or "Start New Policy"
3. **Answer questions** about your organization
4. **Review** the generated context summary
5. **Generate** security policy
6. **Wait** for validation to complete
7. **Download** your approved policy

### Continuing Existing Work

1. **Open** http://localhost:3000
2. **Click** "Continue Existing Context"
3. **Select** your previous work
4. **Review** your answers (you can modify them)
5. **Generate** updated policy

### Understanding Policy Status

- **In Progress**: Policy is being generated
- **Generated**: Ready for validation
- **Under Review**: Validator is checking
- **Revisions Needed**: Return to Policy Agent for updates
- **Approved**: Final policy ready to use

---

## Customizing Your Setup

### Adding Regulatory Documents

The system includes default regulatory data. To add your own:

1. **Create a folder** with your PDF files:
   ```
   documents/
   ├── iso-27001-guidelines.pdf
   ├── gdpr-handbook.pdf
   └── cis-controls.pdf
   ```

2. **Update `.env`**:
   ```env
   CHROMA_COLLECTIONS_PATH=/absolute/path/to/documents
   ```

3. **Index documents**:
   ```bash
   make policy-vectorize
   ```

4. **Wait** for indexing to complete

### Changing Question Templates

Edit the questionnaire configuration:

```bash
# Open the questions file
vim context-agent/config/context-questions.yaml
```

Add or modify questions as needed.

### Adjusting Model Settings

For faster responses (less accurate):
```yaml
# In policy-agent/config/policy-agent.yaml
model: gpt-4o-mini
temperature: 0.7
```

For slower but more accurate responses:
```yaml
model: gpt-4o
temperature: 0.5
```

---

## Troubleshooting

### "Connection refused" Error

**Problem:** Can't connect to services

**Solution:**
```bash
# Check if services are running
docker ps

# Restart everything
make down
make up

# Check logs
make logs
```

### "API Key Invalid" Error

**Problem:** OpenAI API isn't working

**Check:**
1. API key is correct in `.env`
2. Key is active and has credits
3. No typos in the key

### MongoDB Error

**Problem:** Database connection failed

**Solutions:**
```bash
# Restart database
make clean
make up

# Check MongoDB is running
docker ps | grep mongo
```

### Slow Response Times

**Problem:** Policies take too long to generate

**Possible causes:**
- Large policy being generated
- OpenAI API rate limits
- System resource constraints

**Solutions:**
```bash
# Free up resources
make clean
make up

# Use faster model (gpt-4o-mini)
# Edit config files
```

---

## Common Questions

**Q: Can I modify a policy after it's approved?**
A: Yes, download it, edit locally, and re-upload for validation.

**Q: How long does policy generation take?**
A: Usually 1-5 minutes depending on complexity and API speed.

**Q: Can I use different AI models?**
A: Yes! Edit the YAML configuration files to use Claude, Mistral, etc.

**Q: What if validation fails?**
A: The system requests revisions from the Policy Agent automatically (up to 3 times).

**Q: Can multiple users work at the same time?**
A: Yes! Each context has its own unique ID, so multiple users won't interfere.

---

## Next Steps

After your first policy generation:

1. **Explore Configuration**
   - Check out `context-agent/config/examples/`
   - Review YAML structure in each agent directory

2. **Understand the Code**
   - Start with `context-agent/README.md`
   - Then read `policy-agent/README.md`
   - Finally `validator-agent/README.md`

3. **Customize for Your Needs**
   - Add your regulatory documents
   - Modify questions and templates
   - Adjust validation rules

4. **Set Up for Production**
   - See `infrastructure/README.md` for deployment
   - Configure proper backups
   - Set up monitoring

---

## Getting Help

- **Documentation**: Read READMEs in each directory
- **Issues**: Open an issue on GitHub with details
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute

---

## System Requirements

- **Docker & Docker Compose**: Latest stable versions
- **RAM**: At least 4GB
- **Disk Space**: 5GB for images and data
- **OpenAI Account**: With API credits
- **Internet**: For API calls (MongoDB and Chroma use local containers)

---

## What's Next?

- Explore the [Main README](README.md) for architecture details
- Check [CONTRIBUTING.md](CONTRIBUTING.md) to contribute improvements
- Review individual agent READMEs for advanced configuration

**Happy policy generating!** 🚀

