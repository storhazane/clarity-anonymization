# Sample Data

This folder contains sample HRIS data for testing the Slack anonymization application.

### Reducing Re-identification Risk

Create custom anonymized filter names instead of using actual organizational names:

**Teams:**
- Avoid: "Project Phoenix", "Q1 Launch Squad", "Platform Modernization"
- Use: "Team_1", "Team_2", "Team_3"

This prevents external parties from re-identifying individuals by matching known organizational structures.


## Data Filters 

### Team Filter

- Enables comparison of how different teams working on similar initiatives communicate and collaborate
- Reveals differences in communication dynamics between high-performing and low-performing teams

**Example Use Case:**
"Do engineering groups working on Project Phoenix communicate differently from those working on Platform Modernization?"

### Role Filter

- Measures effectiveness of cross-functional collaboration (Engineering ↔ Product ↔ Marketing)
- Establishes function-specific communication baselines that account for role differences (e.g., Engineering requires extended focus periods with minimal interruptions, while Product roles depend on frequent cross-team coordination)

### Optional Filters

#### Work Location

- Remote teams rely primarily on digital messaging
- Onsite workers balance Slack with in-person conversation, naturally posting less online

**Impact:** Prevents mislabeling in-office employees as disengaged due to lower Slack visibility

**Enables:** Accurate comparisons (remote vs. remote, onsite vs. onsite)

#### Employment Status

**Prevents:** Distortion of metrics (e.g., low productivity due to valid absence or departure)

**Enables:** Separate analysis of terminated employees to identify pre-departure communication patterns, post-exit knowledge gaps.

#### Employment Type

**Enables:** Accurate benchmarking by accounting for expected lower activity from part-time workers (prevents misinterpreting reduced hours as disengagement)

#### Tenure Band (automatically calculated from Hire Date)

| Tenure Range | Insight Focus |
|--------------|---------------|
| 0–3 months | Onboarding efficiency |
| 3–6 months | Transition from learning to contributing |
| 6–12 months | Full productivity & increasing influence |
| 1–2 years | Stable communication patterns & confidence |
| 2–5 years | Expert contribution, mentoring expected |
| 5+ years | Early identification of retention risk (drop in engagement may signal quiet quitting) |

## Privacy Protection with K-Anonymity

**K-Anonymity (k=5) Applied to All Fields:**
- **Role, Team, Work_Location, Employment_Status, Employment_Type, Tenure_Band:** Values with <5 occurrences → "Others"
- **Strict Enforcement (Role & Team only):** If "Others" itself has <5 occurrences → entire column becomes "Others"
- **Flexible Enforcement (other fields):** If "Others" has <5 occurrences → values remain grouped as "Others" but are kept

**Why Different Rules?**
- **Role & Team** are critical for analysis precision, so strict k=5 enforcement prevents re-identification
- **Other fields** provide context; allowing small "Others" groups improves data utility


## Usage

Upload this CSV along with a Slack export ZIP to test the anonymization functionality.
