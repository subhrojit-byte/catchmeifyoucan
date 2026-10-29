package catchmeifyoucan.service;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.FraudAction;
import catchmeifyoucan.entity.FraudScenario;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.entity.TransactionOrigin;
import catchmeifyoucan.repository.CompanyRepository;
import catchmeifyoucan.repository.FraudActionRepository;
import catchmeifyoucan.repository.TransactionRepository;
import catchmeifyoucan.simulation.TransactionGenerator;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/** Generates ordinary noise without changing scenario positions or objectives. */
@Service
public class BackgroundTransactionService {

    private final CompanyRepository companyRepository;
    private final TransactionRepository transactionRepository;
    private final FraudActionRepository fraudActionRepository;
    private final int transactionCount;
    private final long seed;

    public BackgroundTransactionService(
            CompanyRepository companyRepository,
            TransactionRepository transactionRepository,
            FraudActionRepository fraudActionRepository,
            @Value("${simulation.background.transaction-count:1}") int transactionCount,
            @Value("${simulation.background.seed:24680}") long seed) {
        this.companyRepository = companyRepository;
        this.transactionRepository = transactionRepository;
        this.fraudActionRepository = fraudActionRepository;
        this.transactionCount = Math.max(transactionCount, 0);
        this.seed = seed;
    }

    public void generateForSuccessfulAction(FraudScenario scenario, FraudAction action) {
        if (Boolean.TRUE.equals(action.getBackgroundTransactionsGenerated())) {
            return;
        }

        List<Company> companies = companyRepository.findAll();
        long scenarioId = scenario.getId() == null ? 0L : scenario.getId();
        long actionSeed = seed ^ (scenarioId * 31L) ^ (long) action.getStep() * 1_000_003L;
        LocalDateTime timestampBase = LocalDateTime.of(2025, 1, 1, 0, 0)
                .plusSeconds(Math.max(scenario.getStep(), 0));
        List<Transaction> transactions = new TransactionGenerator(actionSeed)
                .generateTransactions(
                        companies,
                        transactionCount,
                        TransactionOrigin.BACKGROUND,
                        scenario,
                        null,
                        timestampBase);

        if (!transactions.isEmpty()) {
            transactionRepository.saveAll(transactions);
        }
        action.setBackgroundTransactionsGenerated(true);
        fraudActionRepository.save(action);
    }
}
