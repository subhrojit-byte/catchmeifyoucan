package catchmeifyoucan.controller;

import catchmeifyoucan.dto.TransactionResponse;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.service.TransactionService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/transactions")
public class TransactionController {

    private final TransactionService transactionService;

    public TransactionController(TransactionService transactionService) {
        this.transactionService = transactionService;
    }

    @PostMapping
    public TransactionResponse createTransaction(@RequestBody Transaction transaction) {
        return new TransactionResponse(transactionService.createTransaction(transaction));
    }

    @GetMapping
    public List<TransactionResponse> getAllTransactions() {
        return transactionService.getAllTransactions().stream()
                .map(TransactionResponse::new)
                .toList();
    }

    @GetMapping("/scenario/{scenarioId}")
    public List<TransactionResponse> getScenarioTransactions(@PathVariable Long scenarioId) {
        return transactionService.getScenarioTransactions(scenarioId).stream()
                .map(TransactionResponse::new)
                .toList();
    }

    @GetMapping("/{id}")
    public TransactionResponse getTransaction(@PathVariable Long id) {
        Transaction transaction = transactionService.getTransaction(id);
        return transaction == null ? null : new TransactionResponse(transaction);
    }
}
