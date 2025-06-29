/**
 * Șeptică - Game Interactivity Script
 * Handles card interactions, animations, and game mechanics
 */

document.addEventListener('DOMContentLoaded', function() {
    // Card selection functionality
    const cards = document.querySelectorAll('.playing-card:not(.back)');
    cards.forEach(card => {
        card.addEventListener('click', function() {
            // Toggle selected state
            this.classList.toggle('selected');
            
            // If this is a game that requires selecting only one card at a time
            if (this.classList.contains('selected')) {
                cards.forEach(otherCard => {
                    if (otherCard !== this && otherCard.classList.contains('selected')) {
                        otherCard.classList.remove('selected');
                    }
                });
            }
            
            // You can add AJAX call here to send the selected card to the server
            if (this.classList.contains('selected')) {
                const cardId = this.getAttribute('data-card-id');
                console.log(`Card selected: ${cardId}`);
                
                // Example of how to call the server
                /*
                fetch('/play-card', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        card_id: cardId,
                        game_id: gameId
                    })
                })
                .then(response => response.json())
                .then(data => {
                    // Handle response
                    if (data.success) {
                        // Move card to center
                        moveCardToCenter(this);
                    }
                });
                */
            }
        });
    });
    
    // Function to animate card movement to center
    function moveCardToCenter(cardElement) {
        // Create a clone of the card
        const clone = cardElement.cloneNode(true);
        document.body.appendChild(clone);
        
        // Position the clone at the same position as the original card
        const rect = cardElement.getBoundingClientRect();
        clone.style.position = 'fixed';
        clone.style.top = rect.top + 'px';
        clone.style.left = rect.left + 'px';
        clone.style.margin = '0';
        clone.style.zIndex = '1000';
        
        // Get center pile position
        const centerPile = document.querySelector('.center-pile');
        const centerRect = centerPile.getBoundingClientRect();
        
        // Animate the clone to the center
        clone.style.transition = 'all 0.6s ease-in-out';
        setTimeout(() => {
            clone.style.top = (centerRect.top + centerRect.height/2 - rect.height/2) + 'px';
            clone.style.left = (centerRect.left + centerRect.width/2 - rect.width/2) + 'px';
            clone.style.transform = 'rotate(' + (Math.random() * 20 - 10) + 'deg)';
            
            // Remove the original card
            setTimeout(() => {
                cardElement.remove();
                // After animation completes, leave the clone in the center
            }, 600);
        }, 10);
    }
    
    // Deal cards animation
    function dealCards() {
        const deck = document.querySelector('.card-deck');
        const playerHands = document.querySelectorAll('.player-hand');
        
        let cardCount = 0;
        const totalCards = playerHands.length * 7; // 7 cards per player
        
        for (let i = 0; i < totalCards; i++) {
            setTimeout(() => {
                // Create a card element
                const card = document.createElement('div');
                card.className = 'playing-card back';
                deck.appendChild(card);
                
                // Get position of the card in the deck
                const deckRect = deck.getBoundingClientRect();
                
                // Determine which player gets this card
                const playerIndex = cardCount % playerHands.length;
                const hand = playerHands[playerIndex];
                const handRect = hand.getBoundingClientRect();
                
                // Position card absolutely
                card.style.position = 'fixed';
                card.style.top = deckRect.top + 'px';
                card.style.left = deckRect.left + 'px';
                card.style.margin = '0';
                card.style.zIndex = '1000';
                
                // Animate card to player's hand
                card.style.transition = 'all 0.5s ease';
                setTimeout(() => {
                    card.style.top = handRect.top + 20 + 'px';
                    card.style.left = (handRect.left + 50 + (cardCount % 7) * 30) + 'px';
                    
                    // After card arrives, transform it from back to front
                    setTimeout(() => {
                        card.style.transform = 'rotateY(90deg)';
                        
                        setTimeout(() => {
                            card.classList.remove('back');
                            // Add random card value and suit
                            const suits = ['hearts', 'diamonds', 'clubs', 'spades'];
                            const values = ['A', '7', '8', '9', '10', 'J', 'Q', 'K'];
                            
                            const randomSuit = suits[Math.floor(Math.random() * suits.length)];
                            const randomValue = values[Math.floor(Math.random() * values.length)];
                            
                            card.classList.add(randomSuit);
                            card.innerHTML = `
                                <div class="card-value">${randomValue}</div>
                                <div class="card-suit">${getSuitSymbol(randomSuit)}</div>
                            `;
                            
                            card.style.transform = 'rotateY(0deg)';
                            
                            // Make card interactive
                            card.addEventListener('click', function() {
                                this.classList.toggle('selected');
                            });
                            
                            hand.appendChild(card);
                            card.style.position = 'relative';
                            card.style.top = '0';
                            card.style.left = '0';
                        }, 150);
                    }, 500);
                }, 10);
                
                cardCount++;
            }, i * 200); // Deal cards with delay
        }
    }
    
    // Helper function to get suit symbol
    function getSuitSymbol(suit) {
        switch(suit) {
            case 'hearts': return '♥';
            case 'diamonds': return '♦';
            case 'clubs': return '♣';
            case 'spades': return '♠';
            default: return '';
        }
    }
    
    // If there's a deal button, attach the deal cards function
    const dealButton = document.querySelector('.deal-button');
    if (dealButton) {
        dealButton.addEventListener('click', dealCards);
    }
    
    // Player turn highlight
    function highlightCurrentPlayer(playerIndex) {
        const playerPositions = document.querySelectorAll('.player-position');
        playerPositions.forEach(position => {
            position.querySelector('.player-avatar').classList.remove('player-turn');
        });
        
        if (playerIndex >= 0 && playerIndex < playerPositions.length) {
            playerPositions[playerIndex].querySelector('.player-avatar').classList.add('player-turn');
        }
    }
    
    // Example: highlight first player
    highlightCurrentPlayer(0);
    
    // Set up a simple turn rotation
    let currentPlayerIndex = 0;
    setInterval(() => {
        currentPlayerIndex = (currentPlayerIndex + 1) % 4;
        highlightCurrentPlayer(currentPlayerIndex);
    }, 5000); // Change every 5 seconds for demo
});
