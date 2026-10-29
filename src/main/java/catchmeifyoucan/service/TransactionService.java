package catchmeifyoucan.service;

import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.repository.FraudScenarioRepository;
import catchmeifyoucan.repository.TransactionRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class TransactionService {

    private final TransactionRepository transactionRepository;
    private final FraudScenarioRepository scenarioRepository;

    public TransactionService(TransactionRepository transactionRepository,
                              FraudScenarioRepository scenarioRepository) {
        this.transactionRepository = transactionRepository;
        this.scenarioRepository = scenarioRepository;
    }

    public Transaction createTransaction(Transaction transaction) {
        return transactionRepository.save(transaction);
    }

    public List<Transaction> getAllTransactions() {
        return transactionRepository.findAll();
    }

    public Transaction getTransaction(Long id) {
        return transactionRepository.findById(id).orElse(null);
    }

    public List<Transaction> getScenarioTransactions(Long scenarioId) {
        if (scenarioId == null) {
            throw new IllegalArgumentException("Scenario is required.");
        }
        if (!scenarioRepository.existsById(scenarioId)) {
            throw new IllegalArgumentException("Scenario not found.");
        }
        return transactionRepository.findByScenarioIdOrderByTimestampAscIdAsc(scenarioId);
    }
}
