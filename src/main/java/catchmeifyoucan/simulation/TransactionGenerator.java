package catchmeifyoucan.simulation;

import catchmeifyoucan.entity.Company;
import catchmeifyoucan.entity.Transaction;
import catchmeifyoucan.entity.TransactionOrigin;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.*;

public class TransactionGenerator {

    private final Random random;
    private final Map<Company, List<Company>> businessPartners;
    private static final BigDecimal MAX_NORMAL_TRANSACTION_RATIO =
            BigDecimal.valueOf(0.05);
    private static final int RATIO_SCALE = 8;

    public TransactionGenerator() {
        this.businessPartners =
                new HashMap<>();
        this.random = new Random();
    }

    public TransactionGenerator(long seed) {
        this.businessPartners =
                new HashMap<>();
        this.random = new Random(seed);
    }
    public List<Transaction> generateTransactions(
            List<Company> companies,
            int numberOfTransactions) {

        return generateTransactions(companies, numberOfTransactions,
                TransactionOrigin.INITIAL_BACKGROUND, null, null,
                LocalDateTime.of(2025, 1, 1, 0, 0));
    }

    public List<Transaction> generateTransactions(
            List<Company> inputCompanies,
            int numberOfTransactions,
            TransactionOrigin origin,
            catchmeifyoucan.entity.FraudScenario scenario,
            catchmeifyoucan.entity.FraudAction fraudAction,
            LocalDateTime timestampBase) {

        List<Company> companies = new ArrayList<>(inputCompanies == null
                ? List.of() : inputCompanies);
        companies.sort(Comparator
                .comparing(Company::getId, Comparator.nullsLast(Long::compareTo))
                .thenComparing(company -> company.getCompanyName() == null
                        ? "" : company.getCompanyName()));

        if (companies.size() < 2 || numberOfTransactions <= 0) {
            return new ArrayList<>();
        }

        List<Transaction> transactions =
                new ArrayList<>();

        // Create normal business relationships
        generateBusinessPartners(companies);


        int attempts = 0;
        int maxAttempts =
                numberOfTransactions
                        * Math.max(companies.size(), 1)
                        * 2;

        while (transactions.size() < numberOfTransactions
                && attempts < maxAttempts) {

            attempts++;

            Company sourceCompany;

            Company destinationCompany;


            // Select source company
            sourceCompany =
                    companies.get(
                            random.nextInt(
                                    companies.size()
                            )
                    );


            BigDecimal amount =
                    generateAmount(sourceCompany);

            if (!canHandleTransaction(
                    sourceCompany,
                    amount
            )) {

                continue;
            }


            // Select one of its normal
            // business partners
            if (random.nextDouble() < 0.85) {

                // Normal business transaction

                List<Company> partners =
                        businessPartners.get(
                                sourceCompany
                        );

                destinationCompany =
                        partners.get(
                                random.nextInt(
                                        partners.size()
                                )
                        );

            } else {

                // Occasional transaction outside
                // the normal business network

                do {

                    destinationCompany =
                            companies.get(
                                    random.nextInt(
                                            companies.size()
                                    )
                            );

                } while (
                        destinationCompany.equals(
                                sourceCompany
                        )
                );
            }


            Transaction transaction =
                    new Transaction();


            transaction.setSourceCompany(
                    sourceCompany
            );

            transaction.setDestinationCompany(
                    destinationCompany
            );

            transaction.setAmount(
                    amount
            );

            transaction.setChannel(
                    TransactionChannelGenerator.generateChannel(random)
            );

            transaction.setTimestamp(
                    generateTimestamp(timestampBase)
            );

            transaction.setOrigin(origin);
            transaction.setScenario(scenario);
            transaction.setFraudAction(fraudAction);


            transactions.add(transaction);
        }

        return transactions;
    }


    private BigDecimal generateAmount(Company sourceCompany) {

        if (sourceCompany == null
                || sourceCompany.getAnnualRevenue() == null
                || sourceCompany.getAnnualRevenue()
                .compareTo(BigDecimal.ZERO) <= 0) {

            return BigDecimal.ZERO;
        }

        double percentage =
                0.0001
                        + random.nextDouble() * 0.0099;

        return sourceCompany
                .getAnnualRevenue()
                .multiply(BigDecimal.valueOf(percentage))
                .setScale(2, RoundingMode.HALF_UP);
    }

    private boolean canHandleTransaction(
            Company company,
            BigDecimal amount) {

        if (company == null
                || amount == null
                || company.getAnnualRevenue() == null
                || company.getAnnualRevenue()
                .compareTo(BigDecimal.ZERO) <= 0
                || amount.compareTo(BigDecimal.ZERO) <= 0) {

            return false;
        }

        BigDecimal maximumTransaction =
                company.getAnnualRevenue()
                        .multiply(MAX_NORMAL_TRANSACTION_RATIO);

        return amount.compareTo(maximumTransaction) <= 0;
    }

    private double getTransactionRevenueRatio(
            Company company,
            BigDecimal amount) {

        if (company == null
                || amount == null
                || company.getAnnualRevenue() == null
                || company.getAnnualRevenue()
                .compareTo(BigDecimal.ZERO) <= 0) {

            return 0.0;
        }

        return amount.divide(
                        company.getAnnualRevenue(),
                        RATIO_SCALE,
                        RoundingMode.HALF_UP
                )
                .doubleValue();
    }


    private void generateBusinessPartners(
            List<Company> companies) {

        for (Company company : companies) {

            List<Company> partners =
                    new ArrayList<>();

            int numberOfPartners = Math.min(random.nextInt(4) + 2, companies.size() - 1);

            while (
                    partners.size()
                            < numberOfPartners
            ) {

                Company partner =
                        companies.get(
                                random.nextInt(
                                        companies.size()
                                )
                        );

                if (!partner.equals(company)
                        && !partners.contains(partner)) {

                    partners.add(partner);
                }
            }

            businessPartners.put(
                    company,
                    partners
            );
        }
    }

    private LocalDateTime generateTimestamp(LocalDateTime timestampBase) {

        int daysAgo =
                random.nextInt(365);

        int hour =
                random.nextInt(24);

        int minute =
                random.nextInt(60);

        LocalDateTime base = timestampBase == null
                ? LocalDateTime.of(2025, 1, 1, 0, 0) : timestampBase;
        return base
                .minusDays(daysAgo)
                .withHour(hour)
                .withMinute(minute)
                .withSecond(0)
                .withNano(0);
    }
}
