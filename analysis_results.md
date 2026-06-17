# Pipeline History Evaluation Report

## Run: 2026-04-23 21:51:04 (ID: 1776981064838)
- **Duration**: 1939.0s
- **Overall Pass Rate**: 15/35 (42.9%)
- **Avg Gate A**: 0.625 | **Avg Gate B**: 5.4

### Stage Breakdown
| Stage | Total | Passed | Failed | Pass % | Avg Gate A | Avg Gate B |
|-------|-------|--------|--------|--------|------------|------------|
| BR | 4 | 4 | 0 | 100.0% | 0.787 | 9.0 |
| HLFR | 2 | 2 | 0 | 100.0% | 0.864 | 8.5 |
| LLFR | 1 | 1 | 0 | 100.0% | 0.716 | 8.0 |
| TR | 3 | 0 | 3 | 0.0% | 0.539 | 3.0 |
| TC | 3 | 3 | 0 | 100.0% | 0.752 | 9.3 |

### Common Failure Reasons
**TR Failures:**
- Issues: The output is formatted as a list of verification steps rather than a functional description of the ... | Missing: The sequential nature of the process (steps 1-6) is lost., The specific action of 'receiving' the id...
- Issues: The output completely ignores the functional requirements provided in the input., The output provide... | Missing: Product ID and session ID reception, Validation logic, Cart retrieval, Cart appending, Persistence l...
- Issues: The output completely ignores the functional requirements provided in the input., The output introdu... | Missing: Validation of product existence, Retrieval of shopping cart, Appending product to cart, Persistence ...

---

## Run: 2026-04-28 00:16:15 (ID: 1777335375296)
- **Duration**: 805.0s
- **Overall Pass Rate**: 9/50 (18.0%)
- **Avg Gate A**: 0.721 | **Avg Gate B**: 4.4

### Stage Breakdown
| Stage | Total | Passed | Failed | Pass % | Avg Gate A | Avg Gate B |
|-------|-------|--------|--------|--------|------------|------------|
| BR | 4 | 4 | 0 | 100.0% | 0.826 | 8.0 |
| HLFR | 2 | 2 | 0 | 100.0% | 0.904 | 8.0 |
| LLFR | 1 | 0 | 1 | 0.0% | 0.444 | 2.0 |
| TR | 5 | 0 | 5 | 0.0% | 0.734 | 3.2 |
| TC | 5 | 1 | 4 | 20.0% | 0.705 | 5.0 |

### Common Failure Reasons
**LLFR Failures:**
- Issues: Output is truncated and incomplete., Introduces specific parameters (`userId`, `itemId`, `quantity`)... | Missing: Successful addition of the selected item to the user's shopping cart., The selected item being visib...
**TR Failures:**
- Issues: The output introduces new concepts and system behaviors not present in the input, such as 'checkout ... | Missing: The input's explicit mention of 'system proceeds to error handling' for invalid userId, itemId, and ...
- Issues: The output describes a specific test scenario for updating an item in a shopping cart, rather than t... | Missing: Specific conditions for userId validation failure (null, empty, not registered)., Specific condition...
- Issues: Output describes valid conditions for `itemId` and `quantity`, whereas the input specifies invalid c... | Missing: Input's specified invalid `itemId` conditions (null, empty, or does not correspond to an existing pr...
- Issues: The output describes a specific test scenario for 'quantity' validation, rather than completely repr... | Missing: "System receives a request to add an item", "If `userId` is null, empty, or does not correspond to a...
- Issues: The output introduces the concept of 'available stock' and the scenario of 'quantity exceeding avail... | Missing: Validation for `userId` being null, empty, or not corresponding to a registered user., Validation fo...
**TC Failures:**
- Issues: The output completely omits any verification step for the 'checkout button is enabled' requirement, ... | Missing: Verification that the checkout button is enabled after an item is added to the cart., Verification t...
- Issues: Verification of persistence is incomplete due to truncated step 8., Output does not explicitly verif... | Missing: Explicit verification of the sum of quantities (existing + requested)., Explicit verification of the...
- Issues: Output describes specific test scenarios (e.g., 'Attempt to add item 'PROD-001' with quantity 2 to t... | Missing: The system proceeds to error handling., The system returns a 'User not found' error (HTTP 404)., The...
- Issues: The output describes a test plan to verify the input requirements, rather than representing the syst... | Missing: The system proceeds to error handling (as a system behavior statement), quantity is zero, quantity i...

---

## Run: 2026-04-28 01:12:30 (ID: 1777338750649)
- **Duration**: 1252.2s
- **Overall Pass Rate**: 15/45 (33.3%)
- **Avg Gate A**: 0.660 | **Avg Gate B**: 5.4

### Stage Breakdown
| Stage | Total | Passed | Failed | Pass % | Avg Gate A | Avg Gate B |
|-------|-------|--------|--------|--------|------------|------------|
| BR | 4 | 4 | 0 | 100.0% | 0.803 | 8.8 |
| HLFR | 2 | 2 | 0 | 100.0% | 0.884 | 9.0 |
| LLFR | 2 | 0 | 2 | 0.0% | 0.470 | 3.0 |
| TR | 4 | 0 | 4 | 0.0% | 0.606 | 4.0 |
| TC | 4 | 2 | 2 | 50.0% | 0.745 | 6.8 |

### Common Failure Reasons
**LLFR Failures:**
- Issues: The output provides preparatory steps (input reception, validation, inventory check, existing item c... | Missing: Logic to add a new item to the shopping cart if it doesn't exist., Logic to update the quantity of a...
- Issues: The output describes a completely different functionality (managing checkout button state) than the ... | Missing: Step-by-step logic for placing a selected item into the user's shopping cart., Logic reflecting the ...
**TR Failures:**
- Issues: The output fails to address the requirement to verify product inventory availability (Input Step 4).... | Missing: Verification of product inventory availability check, Verification of the database query for existin...
- Issues: The output introduces a specific '100 unique items' limit which is not present in the input text., T... | Missing: Verification of user_id registration and authentication status, Verification of product_id existence...
- Issues: The output focuses exclusively on the branching logic of adding vs updating (Step 5), but fails to d... | Missing: Verification of user_id authentication and session validity (Input Step 2), Verification of product_...
- Issues: The output fails to define test goals for the specific validation logic provided in the input (user ... | Missing: Verification of user_id authentication and registration status, Verification of product_id existence...
**TC Failures:**
- Issues: The output is truncated and ends mid-sentence., The expected results for the 404 Not Found and 400 B... | Missing: Verification step for 404 Not Found for non-existent product IDs, Verification step for 400 Bad Requ...
- Issues: The output text is truncated mid-sentence at the end ('...updated c')., The final sentence appears t... | Missing: The completion of the final descriptive sentence regarding the success response.

---

## Run: 2026-05-12 09:14:09 (ID: 1778577249439)
- **Duration**: 607.4s
- **Overall Pass Rate**: 30/32 (93.8%)
- **Avg Gate A**: 0.673 | **Avg Gate B**: 7.5

### Stage Breakdown
| Stage | Total | Passed | Failed | Pass % | Avg Gate A | Avg Gate B |
|-------|-------|--------|--------|--------|------------|------------|
| BR | 4 | 4 | 0 | 100.0% | 0.832 | 10.0 |
| HLFR | 2 | 2 | 0 | 100.0% | 0.929 | 9.0 |
| LLFR | 1 | 1 | 0 | 100.0% | 0.593 | 9.0 |
| TR | 7 | 7 | 0 | 100.0% | 0.640 | 6.4 |
| TC | 7 | 7 | 0 | 100.0% | 0.627 | 8.6 |

### Common Failure Reasons
*No failures in this run.*

---

