package catchmeifyoucan.dto;

import catchmeifyoucan.entity.Transaction;
import lombok.Getter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Getter
public class TransactionResponse {
    private final Long id;
    private final CompanyObservationResponse sourceCompany;
    private final CompanyObservationResponse destinationCompany;
    private final BigDecimal amount;
    private final LocalDateTime timestamp;
    private final String description;
    private final String channel;
    private final String origin;
    private final Long scenarioId;
    private final Long fraudActionId;

    public TransactionResponse(Transaction transaction) {
        this.id = transaction.getId();
        this.sourceCompany = new CompanyObservationResponse(transaction.getSourceCompany());
        this.destinationCompany = new CompanyObservationResponse(transaction.getDestinationCompany());
        this.amount = transaction.getAmount();
        this.timestamp = transaction.getTimestamp();
        this.description = transaction.getDescription();
        this.channel = transaction.getChannel();
        this.origin = transaction.getOrigin() == null ? null : transaction.getOrigin().name();
        this.scenarioId = transaction.getScenario() == null ? null : transaction.getScenario().getId();
        this.fraudActionId = transaction.getFraudAction() == null
                ? null : transaction.getFraudAction().getId();
    }
}
